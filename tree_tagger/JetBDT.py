from sklearn import tree, ensemble
import sklearn
#from ipdb import set_trace as st
from matplotlib import pyplot as plt
import numpy as np
import pickle

def make_finite(ary):
    """
    

    Parameters
    ----------
    ary :
        

    Returns
    -------

    
    """
    return np.nan_to_num(ary.astype('float32'))

def begin_training(run, viewer=None):
    """
    

    Parameters
    ----------
    run :
        param viewer: (Default value = None)
    viewer :
        (Default value = None)

    Returns
    -------

    
    """
    assert 'bdt' in run.settings['net_type'].lower();
    # create the dataset
    dataset = run.dataset
    #if not run.empty_run:
    #    bdt = run.last_nets[0]
    #else:
    #print(f"md={run.settings['max_depth']}, ne={run.settings['n_estimators']}")
    dtc = tree.DecisionTreeClassifier(max_depth=run.settings['max_depth'])
    bdt = ensemble.AdaBoostClassifier(dtc, algorithm=run.settings['algorithm_name'],
                             n_estimators=run.settings['n_estimators'])
    bdt.fit(make_finite(dataset.jets), dataset.truth)
    run.last_nets = [bdt]
    run.set_best_state_dicts([pickle.dumps(bdt)])
    run.write()


def make_hist(run):
    """
    

    Parameters
    ----------
    run :
        

    Returns
    -------

    
    """
    output, test_truth = run.apply_to_test()
    plot_range = (output.min(), output.max())
    plt.hist(output[test_truth>0.5],
             bins=10, range=plot_range,
             facecolor='g', label="Signal",
             alpha=.5, edgecolor='k', normed=True)
    plt.hist(output[test_truth<0.5],
             bins=10, range=plot_range,
             facecolor='r', label="Background",
             alpha=.5, edgecolor='k', normed=True)
    plt.ylabel("Percent out")
    plt.xlabel("BDT output")
    plt.title("Jet tagging BDT")
    plt.show()
    return run


def plot_rocs(runs, loglog=False, ax=None):
    """
    

    Parameters
    ----------
    runs :
        param loglog: (Default value = False)
    ax :
        Default value = None)
    loglog :
        (Default value = False)

    Returns
    -------

    
    """
    #axis
    if ax is None:
        _, ax = plt.subplots()
    else:
        ax.clear()
    
    #calculation
    if isinstance(runs, (list, np.ndarray)):
        for run in runs:
            bdt = run.best_nets[0]
            dataset = run.dataset
            outputs = bdt.decision_function(make_finite(dataset.test_jets))
            MC_truth = dataset.test_truth.flatten()
            fpr, tpr, _ = sklearn.metrics.roc_curve(MC_truth, outputs)
            plt.plot(fpr, tpr, label=run.settings['pretty_name'])
        ax.legend()
    else:
        # N.B. except Exception ignorse KeyboardInterrupt, SystemExit and GeneratorExit
        bdt = runs.best_nets[0]
        dataset = runs.dataset
        outputs = bdt.decision_function(make_finite(dataset.test_jets))
        MC_truth = dataset.test_truth.flatten()
        fpr, tpr, _ = sklearn.metrics.roc_curve(MC_truth, outputs)
        plt.plot(fpr, tpr, label=runs.settings['pretty_name'])

    # label
    if loglog:
        ax.loglog()
    ax.set_title("Receiver Operator curve")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")

def feature_importance(run):
    """
    

    Parameters
    ----------
    run :
        

    Returns
    -------

    
    """
    bdt = run.best_nets[0]
    importances = bdt.feature_importances_
    std = np.std([tree.feature_importances_ for tree in bdt.estimators_], axis=0)
    indices = np.argsort(importances)[::-1]
    use = 10
    indices = indices[:use]
    eventWise = run.dataset.eventWise
    jet_name = run.dataset.jet_name
    per_event_columns = [c for c in eventWise.columns
                         if c.startswith("Event_")]
    per_jet_columns = [c for c in eventWise.columns if
                       c.startswith(jet_name + "_Std") or
                       c.startswith(jet_name + "_Ave") or
                       c.startswith(jet_name + "_Sum")]
    names = per_event_columns + per_jet_columns
    names.remove("Event_n")
    names = np.array(names)

    plt.title(f"Feature Importance, first {use}")
    plt.bar(range(len(indices)), importances[indices],
            color=(0.7, 0.2, 0.1), alpha=0.6, yerr=std[indices], align="center")
    plt.xticks(range(len(indices)), names[indices], rotation="vertical")
