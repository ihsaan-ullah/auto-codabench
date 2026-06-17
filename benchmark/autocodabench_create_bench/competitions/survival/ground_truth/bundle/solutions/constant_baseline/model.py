'''
Trivial constant baseline for the Survival competition.

It predicts the same risk score for every patient, which yields a concordance
index of ~0.5 (no better than chance). Its purpose is to *bound* the metric:
any competent submission must beat it. It implements the same interface the
ingestion program expects (fit / predict / save / load), so it runs end-to-end
exactly like a real submission.
'''
import pickle
from os.path import isfile

import numpy as np
from sklearn.base import BaseEstimator


class model(BaseEstimator):
    def __init__(self):
        self.num_train_samples = 0
        self.num_feat = 1
        self.num_labels = 1
        self.is_trained = False
        # The single constant we "predict" for everyone.
        self.constant = 0.0

    def fit(self, X, y):
        '''Learn nothing beyond the shapes; a constant predictor has no parameters.'''
        self.num_train_samples = X.shape[0]
        if X.ndim > 1:
            self.num_feat = X.shape[1]
        if y.ndim > 1:
            self.num_labels = y.shape[1]
        print("FIT: dim(X)= [{:d}, {:d}]".format(self.num_train_samples, self.num_feat))
        self.is_trained = True

    def predict(self, X):
        '''Return the same risk score for every test patient (constant => c-index ~0.5).'''
        num_test_samples = X.shape[0]
        print("PREDICT: dim(X)= [{:d}, {:d}]".format(
            num_test_samples, X.shape[1] if X.ndim > 1 else 1))
        return np.full(num_test_samples, self.constant)

    def save(self, path="./"):
        pickle.dump(self, open(path + '_model.pickle', "wb"))

    def load(self, path="./"):
        modelfile = path + '_model.pickle'
        if isfile(modelfile):
            with open(modelfile, 'rb') as f:
                self = pickle.load(f)
            print("Model reloaded from: " + modelfile)
        return self
