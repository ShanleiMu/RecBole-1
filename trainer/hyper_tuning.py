# -*- coding: utf-8 -*-
# @Time   : 2020/7/19 19:06
# @Author : Shanlei Mu
# @Email  : slmu@ruc.edu.cn
# @File   : hyper_tuning.py

import numpy as np

import hyperopt
from functools import partial
from hyperopt import fmin, tpe, hp, pyll
from hyperopt.base import miscs_update_idxs_vals
from hyperopt.pyll.base import dfs, as_apply
from hyperopt.pyll.stochastic import implicit_stochastic_symbols


"""
Thanks to sbrodeur for the exhaustive search code.
https://github.com/hyperopt/hyperopt/issues/200
"""


class ExhaustiveSearchError(Exception):
    pass


def validate_space_exhaustive_search(space):
    supported_stochastic_symbols = ['randint', 'quniform', 'qloguniform', 'qnormal', 'qlognormal', 'categorical']
    for node in dfs(as_apply(space)):
        if node.name in implicit_stochastic_symbols:
            if node.name not in supported_stochastic_symbols:
                raise ExhaustiveSearchError('Exhaustive search is only possible with the following stochastic symbols: '
                                            '' + ', '.join(supported_stochastic_symbols))


def exhaustive_search(new_ids, domain, trials, seed, nbMaxSucessiveFailures=1000):
    # Build a hash set for previous trials
    hashset = set([hash(frozenset([(key, value[0]) if len(value) > 0 else ((key, None))
                                   for key, value in trial['misc']['vals'].items()])) for trial in trials.trials])

    rng = np.random.RandomState(seed)
    rval = []
    for _, new_id in enumerate(new_ids):
        newSample = False
        nbSucessiveFailures = 0
        while not newSample:
            # -- sample new specs, idxs, vals
            idxs, vals = pyll.rec_eval(
                domain.s_idxs_vals,
                memo={
                    domain.s_new_ids: [new_id],
                    domain.s_rng: rng,
                })
            new_result = domain.new_result()
            new_misc = dict(tid=new_id, cmd=domain.cmd, workdir=domain.workdir)
            miscs_update_idxs_vals([new_misc], idxs, vals)

            # Compare with previous hashes
            h = hash(frozenset([(key, value[0]) if len(value) > 0 else (
                (key, None)) for key, value in vals.items()]))
            if h not in hashset:
                newSample = True
            else:
                # Duplicated sample, ignore
                nbSucessiveFailures += 1

            if nbSucessiveFailures > nbMaxSucessiveFailures:
                # No more samples to produce
                return []

        rval.extend(trials.new_trial_docs([new_id],
                                          [None], [new_result], [new_misc]))
    return rval


class HyperTuning(object):
    def __init__(self, objective_function, space=None, params_file=None, algo=tpe.suggest, max_evals=100):
        self.best_score = None
        self.best_params = None
        self.best_test_result = None
        self.params2result = {}

        self.objective_function = objective_function
        self.max_evals = max_evals
        if space:
            self.space = space
        elif params_file:
            self.space = self._build_space_from_file(params_file)
        else:
            raise ValueError('at least one of `space` and `params_file` is provided')
        if isinstance(algo, str):
            if algo == 'exhaustive':
                self.algo = partial(exhaustive_search, nbMaxSucessiveFailures=1000)
                self.max_evals = np.inf
            else:
                raise ValueError('Illegal algo [{}]'.format(algo))
        else:
            self.algo = algo

    @staticmethod
    def _build_space_from_file(file):
        space = {}
        with open(file, 'r') as fp:
            for line in fp:
                para_name, para_type, para_value = line.strip().split(' ')
                if para_type == 'choice':
                    para_value = eval(para_value)
                    space[para_name] = hp.choice(para_name, para_value)
                elif para_type == 'uniform':
                    low, high = para_value.strip().split(',')
                    space[para_name] = hp.uniform(para_name, float(low), float(high))
                elif para_type == 'quniform':
                    low, high, q = para_value.strip().split(',')
                    space[para_name] = hp.quniform(para_name, float(low), float(high), float(q))
                elif para_type == 'loguniform':
                    low, high = para_value.strip().split(',')
                    space[para_name] = hp.loguniform(para_name, float(low), float(high))
                else:
                    raise ValueError('Illegal param type [{}]'.format(para_type))
        return space

    @staticmethod
    def params2str(params):
        params_str = ''
        for param_name in params:
            params_str += param_name + ':' + str(params[param_name]) + ', '
        return params_str[:-2]

    def trial(self, params):
        config_dict = params
        params_str = self.params2str(params)
        result_dict = self.objective_function(config_dict)
        self.params2result[params_str] = result_dict
        score, bigger = result_dict['best_valid_score'], result_dict['valid_score_bigger']

        if not self.best_score:
            self.best_score = score
            self.best_params = params
        else:
            if bigger:
                if score > self.best_score:
                    self.best_score = score
                    self.best_params = params
            else:
                if score < self.best_score:
                    self.best_score = score
                    self.best_params = params

        if bigger:
            score = - score
        return {'loss': score, 'status': hyperopt.STATUS_OK}

    def run(self):
        fmin(self.trial, self.space, algo=self.algo, max_evals=self.max_evals)