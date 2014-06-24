"""
The main script to test the accuracy on birds
"""

import cPickle as pickle
from iceberk import mpi, visiondata, datasets, pipeline, classifier
import numpy as np
import logging
import gflags
import os,sys

# local import
import tax
import treereg

########
# Settings
########

ROOT = "/u/vis/x1/common/CIFAR/cifar-100-python/"
FEATDIR = "/u/vis/ttmp/jiayq/cifar100/"
MIRRORED = False
CONV = pipeline.ConvLayer(
    [pipeline.PatchExtractor([6,6], 1),
     pipeline.MeanvarNormalizer({'reg': 10}),
     pipeline.LinearEncoder({},
                trainer = pipeline.ZcaTrainer({'reg': 0.1})),
     pipeline.ThresholdEncoder({},
                trainer = pipeline.OMPTrainer({'k':1024, 'max_iter':100})),
     #pipeline.PyramidPooler({'level': 3, 'method': 'max'})
     pipeline.SpatialPooler({'grid': (2,2), 'method': 'ave'})
    ], fixed_size = True)

########
# Main script
########
gflags.DEFINE_bool("extract", False, 
                   "If set, train the feature extraction pipeline.")
gflags.DEFINE_bool("flat", False,
                   "If set, perform flat classification.")
gflags.DEFINE_bool("hier", False, 
                   "If set, perform hierarchical classification.")
gflags.DEFINE_bool("treereg", False,
                   "If set, perform classification with tree regularization.")
gflags.DEFINE_float("reg", 0.01,
                   "The regularization term used in the classification.")
gflags.FLAGS(sys.argv)
FLAGS = gflags.FLAGS
mpi.root_log_level(level=logging.DEBUG)

if FLAGS.extract:
    train_data = visiondata.CifarDataset(ROOT, True)
    test_data = visiondata.CifarDataset(ROOT, False)
    if MIRRORED:
        train_data = datasets.MirrorSet(train_data)
    CONV.train(train_data, 400000, exhaustive = True)
    mpi.root_pickle(CONV, __file__ + ".conv.pickle")
    Xtrain = CONV.process_dataset(train_data, as_2d = True)
    Xtest = CONV.process_dataset(test_data, as_2d = True)
    Ytrain = train_data.labels()
    Ytest = test_data.labels()
    m, std = classifier.feature_meanstd(Xtrain)
    Xtrain -= m
    Xtrain /= std
    Xtest -= m
    Xtest /= std
    mpi.dump_matrix_multi(Xtrain, os.path.join(FEATDIR,'Xtrain'))
    mpi.dump_matrix_multi(Xtest, os.path.join(FEATDIR,'Xtest'))
    mpi.dump_matrix_multi(Ytrain, os.path.join(FEATDIR,'Ytrain'))
    mpi.dump_matrix_multi(Ytest, os.path.join(FEATDIR,'Ytest'))
else:
    Xtrain = mpi.load_matrix_multi(os.path.join(FEATDIR,'Xtrain'))
    Xtest = mpi.load_matrix_multi(os.path.join(FEATDIR,'Xtest'))
    Ytrain = mpi.load_matrix_multi(os.path.join(FEATDIR,'Ytrain'))
    Ytest = mpi.load_matrix_multi(os.path.join(FEATDIR,'Ytest'))

if FLAGS.flat:
    logging.info("Performing flat classification")
    solver = classifier.SolverMC(FLAGS.reg,
                                 classifier.Loss.loss_multiclass_logistic,
                                 classifier.Reg.reg_l2,
                                 fminargs = {'maxfun': 1000})
    w,b = solver.solve(Xtrain, classifier.to_one_of_k_coding(Ytrain, fill=0))
    pred = np.dot(Xtrain, w) + b
    accu_train = classifier.Evaluator.accuracy(Ytrain, pred)
    pred = np.dot(Xtest, w) + b
    accu_test = classifier.Evaluator.accuracy(Ytest, pred)
    logging.info("Reg %f, train accu %f, test accu %f" % \
            (FLAGS.reg, accu_train, accu_test))
    mpi.root_pickle((w, b, FLAGS.reg, accu_train, accu_test),
                    __file__ + str(FLAGS.reg) + ".flat.pickle")

if gflags.FLAGS.hier:
    logging.info("Performing hierarchical classification")
    utility = np.exp(tax.cifar_info_gain())
    utility /= utility.sum(axis=1)[:, np.newaxis]
    solver = classifier.SolverMC(FLAGS.reg,
                                 classifier.Loss.loss_multiclass_logistic,
                                 classifier.Reg.reg_l2,
                                 fminargs = {'maxfun': 1000})
    w,b = solver.solve(Xtrain, 
            np.ascontiguousarray(utility[Ytrain.astype(int)]))
    pred = np.dot(Xtrain, w) + b
    accu_train = classifier.Evaluator.accuracy(Ytrain, pred)
    pred = np.dot(Xtest, w) + b
    accu_test = classifier.Evaluator.accuracy(Ytest, pred)
    logging.info("Reg %f, train accu %f, test accu %f" % \
            (FLAGS.reg, accu_train, accu_test))
    mpi.root_pickle((w, b, FLAGS.reg, accu_train, accu_test),
                    __file__ + str(FLAGS.reg) + ".hier.pickle")

if FLAGS.treereg:
    logging.info("Performing tree-regularized classification")
    tree = tax.get_cifar_ancestor_matrix()
    solver = treereg.SolverTreeReg(FLAGS.reg,
            classifier.Loss.loss_multiclass_logistic,
            classifier.Reg.reg_l2,
            fminargs = {'maxfun': 1000},
            regargs = {'tree': tree})
    whidden,b = solver.solve(Xtrain,
            classifier.to_one_of_k_coding(Ytrain, fill=0))
    w = np.dot(whidden, tree)
    pred = np.dot(Xtrain, w) + b
    accu_train = classifier.Evaluator.accuracy(Ytrain, pred)
    pred = np.dot(Xtest, w) + b
    accu_test = classifier.Evaluator.accuracy(Ytest, pred)
    logging.info("Reg %f, train accu %f, test accu %f" % \
            (FLAGS.reg, accu_train, accu_test))
    mpi.root_pickle((w, b, FLAGS.reg, accu_train, accu_test),
                    __file__ + str(FLAGS.reg) + ".treereg.pickle")
