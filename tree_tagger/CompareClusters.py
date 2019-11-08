""" compare two jet clustering techniques """
from ipdb import set_trace as st
from tree_tagger import Components, TrueTag
import sklearn.metrics
import sklearn.preprocessing
from matplotlib import pyplot as plt
import numpy as np

def rand_score(eventWise, jet_name1, jet_name2):
    # two jets clustered from the same eventWise should have
    # the same JetInput_SourceIdx, 
    # if I change this in the future I need to update this function
    selection1 = getattr(eventWise, jet_name1+"_InputIdx")
    selection2 = getattr(eventWise, jet_name2+"_InputIdx")
    num_common_events = min(len(selection1), len(selection2))
    num_inputs_per_event = Components.apply_array_func(len, eventWise.JetInputs_SourceIdx[:num_common_events])
    scores = []
    for event_n, n_inputs in enumerate(num_inputs_per_event):
        labels1 = -np.ones(n_inputs)
        for i, jet in enumerate(selection1[event_n]):
            labels1[jet[jet < n_inputs]] = i
        assert -1 not in labels1
        labels2 = -np.ones(n_inputs)
        for i, jet in enumerate(selection2[event_n]):
            labels2[jet[jet < n_inputs]] = i
        assert -1 not in labels2
        score = sklearn.metrics.adjusted_rand_score(labels1, labels2)
        scores.append(score)
    return scores

def visulise_scores(scores, jet_name1, jet_name2, score_name="Rand score"):
    plt.hist(scores, bins=40, density=True, histtype='stepfilled')
    mean = np.mean(scores)
    std = np.std(scores)
    plt.vlines([mean - 2*std, mean, mean + 2*std], 0, 1, colors=['orange', 'red', 'orange'])
    plt.xlabel(score_name)
    plt.ylabel("Density")
    plt.title(f"Similarity of {jet_name1} and {jet_name2} (for {len(scores)} events)")



def pseudovariable_differences(eventWise, jet_name1, jet_name2, var_name="Rapidity"):
    eventWise.selected_index = None
    selection1 = getattr(eventWise, jet_name1+"_InputIdx")
    selection2 = getattr(eventWise, jet_name2+"_InputIdx")
    var1 = getattr(eventWise, jet_name1 + "_" + var_name)
    var2 = getattr(eventWise, jet_name2 + "_" + var_name)
    num_common_events = min(len(selection1), len(selection2))
    num_inputs_per_event = Components.apply_array_func(len, eventWise.JetInputs_SourceIdx[:num_common_events])
    pseudojet_vars1 = []
    pseudojet_vars2 = []
    num_unconnected = 0
    for event_n, n_inputs in enumerate(num_inputs_per_event):
        values1 = {}
        for i, jet in enumerate(selection1[event_n]):
            children = tuple(sorted(jet[jet < n_inputs]))
            values = sorted(var1[event_n, i, jet >= n_inputs])
            values1[children] = values
        values2 = {}
        for i, jet in enumerate(selection2[event_n]):
            children = tuple(sorted(jet[jet < n_inputs]))
            values = sorted(var2[event_n, i, jet >= n_inputs])
            values2[children] = values
        for key1 in values1.keys():
            if key1 in values2:
                pseudojet_vars1+=values2[key1]
                pseudojet_vars2+=values2[key1]
            else:
                num_unconnected += 1
    pseudojet_vars1 = np.array(pseudojet_vars1)
    pseudojet_vars2 = np.array(pseudojet_vars2)
    return pseudojet_vars1, pseudojet_vars2, num_unconnected


def fit_to_tags(eventWise, jet_name, event_n=None, tag_pids=None):
    if event_n is None:
        assert eventWise.selected_index is not None
    else:
        eventWise.selected_index = event_n
    inputidx_name = jet_name + "_InputIdx"
    rootinputidx_name = jet_name+"_RootInputIdx"
    jet_rapidity = eventWise.match_indices(jet_name+"_Rapidity", inputidx_name, rootinputidx_name)
    jet_phi = eventWise.match_indices(jet_name+"_Phi", inputidx_name, rootinputidx_name)
    jet_pt = eventWise.match_indices(jet_name+"_PT", inputidx_name, rootinputidx_name)

    tag_idx = TrueTag.tag_particle_indices(eventWise, tag_pids=tag_pids)
    tag_rapidity = eventWise.Rapidity[tag_idx]
    tag_phi = eventWise.Phi[tag_idx]
    tag_pt = eventWise.PT[tag_idx]
    # normalise the tag_pt and jet_pts, it's reasonable to think these could be corrected to match
    normed_jet_pt = sklearn.preprocessing.normalize(jet_pt)
    normed_tag_pt = sklearn.preprocessing.normalize(tag_pt)
    # divide tag and jet rapidity by the abs mean of both, effectivly collectivly normalising them
    abs_mean = np.mean(np.mean(np.abs(jet_rapidity)), np.mean(np.abs(tag_rapidity)))
    normed_jet_rapidity = jet_rapidity/abs_mean
    normed_tag_rapidity = tag_rapidity/abs_mean
    # divide the phi coordinates by pi for the same effect
    normed_jet_phi = 2*jet_phi/np.pi
    normed_tag_phi = 2*tag_phi/np.pi
    # find angular distances as they are invarient of choices
    phi_distance = np.vstack([[j_phi - t_phi for j_phi in normed_jet_phi]
                             for t_phi in normed_tag_phi])
    # remeber that these vlaues are normalised
    phi_distance[phi_distance > 2] = 4 - phi_distance[phi_distance > np.pi]
    rapidity_distance = np.vstack([[j_rapidity - t_rapidity for j_rapidity in normed_jet_rapidity]
                                   for t_rapidity in normed_tag_rapidity])
    angle_dist2 = np.square(phi_distance) + np.square(rapidity_distance)
    # starting with the highest PT tag working to the lowest PT tag
    # assign tags to jets and recalculate the distance as needed
    matched_jet = np.zeros_like(tag_pt, dtype=int) - 1
    current_pt_offset_for_jet = -np.copy(normed_jet_pt)
    for tag_idx in np.argsort(tag_pt):
        this_pt = normed_tag_pt[tag_idx]
        new_pt_dist2 = np.square(current_pt_offset_for_jet + this_pt)
        allocate_to = np.argmin(new_pt_dist2 + angle_dist2)
        matched_jet[tag_idx] = allocate_to
        current_pt_offset_for_jet[allocate_to] += this_pt
    # now calculate the real distance
    deltaPhi_closest_jets = np.array([np.abs(t_phi - jet_phi[c]) for t_phi, c in zip(tag_phi, matched_jet)])
    deltaRapidity_closest_jets = np.array([np.abs(t_rapidity - jet_rapidity[c]) for t_rapidity, c in zip(tag_rapidity, matched_jet)])
    deltaPT_closest_jets = np.array([np.abs(t_pt - jet_pt[c]) for t_pt, c in zip(tag_pt, matched_jet)])
    return deltaPT_closest_jets, deltaPhi_closest_jets, deltaRapidity_closest_jets
    

    
    

