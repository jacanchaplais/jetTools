# TODO need to rotat the jets
""" Preprocessig module takes prepared datafiles and performed generic processing tasks requird beofre data can be run as a net """
import numpy as np
#from ipdb import set_trace as st
from sklearn import preprocessing
import os
import awkward
from tree_tagger import Components
from tree_tagger.Components import flatten, apply_array_func

def phi_rotation(eventWise):
    """
    

    Parameters
    ----------
    eventWise :
        

    Returns
    -------

    
    """
    eventWise.selected_index = None
    content = {}
    # pick out the columns to transform
    pxy_cols = [(c, c.replace('Px', 'Py').replace('px', 'py'))
                for c in eventWise.columns if "px" in c.lower()]
    phi_cols = [c for c in eventWise.columns if "phi" in c.lower()]
    content = {c:[] for c in phi_cols}
    for px_name, py_name in pxy_cols:
        content[px_name] = []
        content[py_name] = []
    # now rotate the events about the z axis
    # so that the overall momentum is down the x axis
    children = eventWise.Children
    no_decendants = apply_array_func(lambda lst: not bool(len(lst)), children, depth=Components.EventWise.EVENT_DEPTH)
    pxs = eventWise.Px
    pys = eventWise.Py
    def leaf_sum(values, no_dez):
        """
        

        Parameters
        ----------
        values :
            param no_dez:
        no_dez :
            

        Returns
        -------

        
        """
        return np.sum(values[no_dez])
    px_sums = apply_array_func(leaf_sum, pxs, no_decendants)
    py_sums = apply_array_func(leaf_sum, pys, no_decendants)
    for event_n, (px, py) in enumerate(zip(px_sums, py_sums)):
        remove_cols = []
        eventWise.selected_index = event_n
        angle = np.arctan(py/px)
        cos = np.cos(angle)
        sin = np.sin(angle)
        def rotate_x(xs, ys):
            """
            

            Parameters
            ----------
            xs :
                param ys:
            ys :
                

            Returns
            -------

            
            """
            return xs*cos - ys*sin
        def rotate_y(xs, ys):
            """
            

            Parameters
            ----------
            xs :
                param ys:
            ys :
                

            Returns
            -------

            
            """
            return xs*sin + ys*cos
        def rotate_phi(phis): 
            """
            

            Parameters
            ----------
            phis :
                

            Returns
            -------

            
            """
            return Components.confine_angle(phis - angle) 
        for px_name, py_name in pxy_cols:
            try:
                this_pxs = getattr(eventWise, px_name)
                this_pys = getattr(eventWise, py_name)
                content[px_name].append(rotate_x(this_pxs, this_pys))
                content[py_name].append(rotate_y(this_pxs, this_pys))
            except IndexError:
                remove_cols.append((px_name, py_name))
        for pair in remove_cols:
            pxy_cols.remove(pair)
        remove_cols = []
        for phi_name in phi_cols:
            try:
                this_phis = getattr(eventWise, phi_name)
                content[phi_name].append(rotate_phi(this_phis))
            except IndexError:
                remove_cols.append(phi_name)
        for name in remove_cols:
            phi_cols.remove(name)
    content = {name: awkward.fromiter(a) for name, a in content.items()}
    eventWise.append(**content)


def normalize_jets(eventWise, jet_name, new_name):
    """
    

    Parameters
    ----------
    eventWise :
        param jet_name:
    new_name :
        
    jet_name :
        

    Returns
    -------

    
    """
    eventWise.selected_index = None
    jet_cols = [(c, c.replace(jet_name, new_name))
                for c in eventWise.columns if jet_name in c]
    normed_outs = {}
    for name, new_name in jet_cols:
        values = getattr(eventWise, name)
        flat_iter = flatten(values)
        first = next(flat_iter)
        # we ony want to normalise flaot columns
        if isinstance(first, (float, np.float)):
            print(f"Norming {name}")
            flat_values = [first] + [i for i in flat_iter]
            flat_values = np.array(flat_values).reshape((-1, 1))
            transformer = preprocessing.RobustScaler().fit(flat_values)
            def rescale(vals):
                """
                

                Parameters
                ----------
                vals :
                    

                Returns
                -------

                
                """
                if len(vals) == 0:
                    return vals
                return transformer.transform(np.array(vals).reshape((-1, 1)))
            out = apply_array_func(rescale, values)  # mixed depth if summary vars present
            normed_outs[new_name] = out
    eventWise.append(**normed_outs)


def set_min_tracks(eventWise, jet_name, new_name, min_tracks=3):
    """
    

    Parameters
    ----------
    eventWise :
        param jet_name:
    new_name :
        param min_tracks: (Default value = 3)
    jet_name :
        
    min_tracks :
        (Default value = 3)

    Returns
    -------

    
    """
    eventWise.selected_index = None
    jet_cols = [(c, c.replace(jet_name, new_name))
                for c in eventWise.columns if c.startswith(jet_name)]
    per_track_var = getattr(eventWise, jet_name+"_Energy")
    n_events = len(per_track_var)
    mask = apply_array_func(lambda lst: len(lst)>=min_tracks, per_track_var, depth=eventWise.JET_DEPTH)
    filtered_outs = {}
    for name, new_name in jet_cols:
        print(f"Filtering {name}")
        values = []
        for event_n, mask_here in enumerate(mask):
            eventWise.selected_index = event_n
            values_here = getattr(eventWise, name)
            values.append(values_here[mask_here])
        filtered_outs[new_name] = awkward.fromiter(values)
    eventWise.append(**filtered_outs)


def make_targets(eventWise, jet_name):
    """
    anything with at least one tag is considered signal

    Parameters
    ----------
    eventWise :
        param jet_name:
    jet_name :
        

    Returns
    -------

    
    """
    truth_tags = getattr(eventWise, jet_name+"_Tags")
    def target_func(array):
        """
        

        Parameters
        ----------
        array :
            

        Returns
        -------

        
        """
        return len(array) > 0
    contents = {jet_name + "_Target": apply_array_func(target_func, truth_tags, depth=eventWise.EVENT_DEPTH)}
    eventWise.append(**contents)


def event_wide_observables(eventWise):
    """
    

    Parameters
    ----------
    eventWise :
        

    Returns
    -------

    
    """
    contents = {}
    cumulative_columns = ["Energy", "Rapidity", "PT",
                          "Px", "Py", "Pz"]
    eventWise.selected_index = None
    for name  in cumulative_columns:
        # sometimes the num of a jagged array works like a concatination
        values = getattr(eventWise, name)
        values = apply_array_func(np.nan_to_num, values, depth=eventWise.EVENT_DEPTH)
        contents["Event_Sum"+name] = apply_array_func(np.sum, values, depth=eventWise.EVENT_DEPTH)
        contents["Event_Ave"+name] = apply_array_func(np.mean, values, depth=eventWise.EVENT_DEPTH)
        contents["Event_Std"+name] = apply_array_func(np.std, values, depth=eventWise.EVENT_DEPTH)
    eventWise.selected_index = None
    eventWise.append(**contents)


def jet_wide_observables(eventWise, jet_name):
    """
    

    Parameters
    ----------
    eventWise :
        param jet_name:
    jet_name :
        

    Returns
    -------

    
    """
    # calculate averages and num hits
    eventWise.selected_index = None
    cumulative_components = ["PT", "Rapidity", "PseudoRapidity",
                             "Theta", "Phi", "Energy",
                             "Px", "Py", "Pz",
                             "JoinDistance"]
    contents = {}
    eventWise.selected_index = None
    n_events = len(getattr(eventWise, jet_name+"_Energy"))
    for name in cumulative_components:
        col_name = jet_name + '_' + name
        # sometimes the num of a jagged array works like a concatination
        values = getattr(eventWise, col_name)
        values = apply_array_func(np.nan_to_num, values, depth=eventWise.JET_DEPTH)
        # goes funky on jagged arrays
        contents[jet_name+"_Sum"+name] = apply_array_func(lambda lst: np.sum(lst.tolist()),
                                                          values, depth=eventWise.JET_DEPTH)
        contents[jet_name+"_Ave"+name] = apply_array_func(lambda lst: np.mean(lst.tolist()),
                                                          values, depth=eventWise.JET_DEPTH)
        contents[jet_name+"_Std"+name] = apply_array_func(lambda lst: np.std(lst.tolist()),
                                                          values, depth=eventWise.JET_DEPTH)
    # num_hits
    eventWise.selected_index = None
    contents[jet_name+"_size"] = apply_array_func(len, values, depth=eventWise.JET_DEPTH)
    eventWise.append(**contents)


