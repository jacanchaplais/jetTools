""" Tools to turn clusters of particles into showers """
import os
from ipdb import set_trace as st
from tree_tagger import PDGNames, DrawTrees, Components
import itertools
from matplotlib import pyplot as plt
import numpy as np
import awkward


def descendant_idxs(eventWise, *start_idxs):
    """
    

    Parameters
    ----------
    eventWise :
        
    *start_idxs :
        

    Returns
    -------

    """
    assert eventWise.selected_index is not None
    final_idxs = set()
    stack = list(start_idxs)
    while stack:
        idx = stack.pop()
        children = eventWise.Children[idx].tolist()
        stack += children
        if not children:
            final_idxs.add(idx)
    return final_idxs


def append_b_idxs(eventWise, silent=True, append=True):
    """
    

    Parameters
    ----------
    eventWise :
        
    silent :
         (Default value = True)
    append :
         (Default value = True)

    Returns
    -------

    """
    eventWise.selected_index = None
    name = "BQuarkIdx"
    n_events = len(eventWise.MCPID)
    bidxs = list(getattr(eventWise, name, []))
    start_point = len(bidxs)
    if start_point >= n_events:
        print("Finished")
        return True
    end_point = n_events
    if not silent:
        print(f" Will stop at {end_point/n_events:.1%}")
    for event_n in range(start_point, end_point):
        if event_n % 10 == 0 and not silent:
            print(f"{event_n/n_events:.1%}", end='\r', flush=True)
        if os.path.exists("stop"):
            print(f"Completed event {event_n-1}")
            break
        eventWise.selected_index = event_n
        # obtain 4 unique b-quarks
        b_idxs = np.where(np.abs(eventWise.MCPID) == 5)[0]
        no_b_children = [len(set(children).intersection(b_idxs)) == 0
                         for children in eventWise.Children[b_idxs]]
        bidxs.append(b_idxs[no_b_children])
    bidxs = awkward.fromiter(bidxs)
    content = {name: bidxs}
    if append:
        eventWise.append(**content)
    return content


class Shower:
    """
    Object to hold a shower of particles
    
    only keeps a list of the particle particle_idxs, parents, children and PDGparticle_idxs.

    Parameters
    ----------

    Returns
    -------

    
    """
    def __init__(self, particle_idxs, parents, children, labels, amalgam=False):
        self.amalgam = amalgam
        self.particle_idxs = awkward.fromiter(particle_idxs)
        self.parents = awkward.fromiter(parents)
        self.children = awkward.fromiter(children)
        self.labels = awkward.fromiter(labels)
        self.ranks = None  # exspensive, create as needed with find_ranks()
        self._find_roots()

    def __len__(self):
        return len(self.particle_idxs)

    def amalgamate(self, other_shower):
        """
        

        Parameters
        ----------
        other_shower :
            

        Returns
        -------

        
        """
        self.amalgam = True
        total_particle_idxs = len(set(self.particle_idxs).union(set(other_shower.particle_idxs)))
        next_free_sIndex = len(self.particle_idxs)
        # prep the existing column
        new_idxs = np.empty(total_particle_idxs, dtype=int)
        new_idxs[:len(self.particle_idxs)] = self.particle_idxs
        self.particle_idxs = new_idxs
        new_labels = np.empty(total_particle_idxs, dtype=str)
        new_labels[:len(self.labels)] = self.labels
        self.labels = new_labels
        try:
            self.parents = self.parents.tolist()
        except AttributeError:
            pass
        try:
            self.children = self.children.tolist()
        except AttributeError:
            pass
        for oIndex, oID in enumerate(other_shower.particle_idxs):
            if oID in self.particle_idxs:  #check for agreement
                sIndex = list(self.particle_idxs).index(oID)
                assert self.parents[sIndex] == other_shower.parents[oIndex]
                assert self.children[sIndex] == other_shower.children[oIndex]
                assert self.labels[sIndex] == other_shower.labels[oIndex]
            else:  # add it on
                sIndex = next_free_sIndex
                next_free_sIndex += 1
                self.particle_idxs[sIndex] = oID
                self.parents.append(other_shower.parents[oIndex])
                self.children.append(other_shower.children[oIndex])
                self.labels[sIndex] = other_shower.labels[oIndex]
        self._find_roots()

    @property
    def n_particles(self):
        """int: the number of particles at all points of the shower"""
        return len(self.particle_idxs)

    def _find_roots(self):
        """
        Demand the shower identify it's root.
        This is stored as an internal variable.

        Parameters
        ----------

        Returns
        -------

        
        """
        root_idxs = get_roots(self.particle_idxs, self.parents)
        if not self.amalgam and len(self.particle_idxs):
            assert len(root_idxs) == 1, "There should only be one root to a shower"
        self.root_idxs = root_idxs
        list_idxs = list(self.particle_idxs)
        self.root_local_idxs = [list_idxs.index(r) for r in root_idxs]

    @property
    def roots(self):
        """ """
        msg = "changed to root_idxs or root_local_idxs for clarity"
        raise AttributeError(msg)

    def find_ranks(self):
        """
        Demand the shower identify the rang of each particle.
        The rank of a particle is the length of the shortest distance to the root.

        Parameters
        ----------

        Returns
        -------

        
        """
        # put the first rank in
        current_rank = self.root_local_idxs  
        rank_n = 0
        ranks = np.full_like(self.particle_idxs, -1, dtype=int)
        ranks[current_rank] = rank_n
        list_particle_idxs = list(self.particle_idxs)  # somtimes this is an array
        has_decendants = True
        while has_decendants:
            rank_n += 1
            decendant_particles = [child for index in current_rank
                                   for child in self.children[index]
                                   if child in self.particle_idxs]
            current_rank = []
            for child in decendant_particles:
                index = list_particle_idxs.index(child)
                # don't overwite a rank, so in a loop the lowers rank stands
                # also needed to prevent perpetual loops
                if ranks[index] == -1:
                    current_rank.append(index)
            ranks[current_rank] = rank_n
            has_decendants = len(current_rank) > 0
        assert -1 not in ranks
        rank_n -= 1  # will have incremented it one time too many
        # finally, promote all end state particles to the highest rank
        ends = self.ends
        ranks[[i in ends for i in self.particle_idxs]] = rank_n
        self.ranks = ranks
        return ranks

    def graph(self):
        """Turn the shower into a dotgraph"""
        assert len(self.particle_idxs) == len(self.parents)
        assert len(self.particle_idxs) == len(self.children)
        assert len(self.particle_idxs) == len(self.labels)
        return DrawTrees.DotGraph(self)

    @property
    def outside_connections(self):
        """ """
        raise AttributeError("you want outside_connection_idxs, but check you are useing particle_idx not local shower index")

    @property
    def outside_connection_idxs(self):
        """
        Function that anouches which particles have perantage from outside this shower
        Includes the root

        Parameters
        ----------

        Returns
        -------

        
        """
        outside_idxs = []
        for idx, parents_here in zip(self.particle_idxs, self.parents):
            if not np.all([m in self.particle_idxs for m in parents_here]):
                outside_idxs.append(idx)
        return outside_idxs
    
    @property
    def ends(self):
        """ global idxs not local """
        _ends = []
        for i, children_here in enumerate(self.children):
            if np.all([child is None for child in children_here]):
                _ends.append(self.particle_idxs[i])
        return _ends

    @property
    def flavour(self):
        """ """
        flavours = self.labels[self.root_local_idxs]
        return '+'.join(flavours)


def upper_layers(eventWise, n_layers=5, capture_pids=[]):
    """
    Make a shower of just the topmost layers of the event

    Parameters
    ----------
    eventWise :
        
    n_layers :
         (Default value = 5)
    capture_pids :
         (Default value = [])

    Returns
    -------

    """
    assert eventWise.selected_index is not None
    n_particles = len(eventWise.Parents)
    # start from the roots
    particle_idxs = set(get_roots(list(range(n_particles)), eventWise.Parents))
    current_layer = [*particle_idxs]  # copy it into a new layer
    locations_to_capture = {i for i, pid in enumerate(eventWise.MCPID) if pid in capture_pids}
    layer_reached = 1
    while locations_to_capture or layer_reached < n_layers:
        children = set(eventWise.Children[current_layer].flatten())
        locations_to_capture.difference_update(children)
        particle_idxs.update(children)
        current_layer = list(children)
        layer_reached += 1
    particle_idxs = list(particle_idxs)
    labeler = PDGNames.IDConverter()
    labels = [labeler[pid] for pid in eventWise.MCPID[particle_idxs]]
    shower = Shower(particle_idxs, eventWise.Parents[particle_idxs],
                    eventWise.Children[particle_idxs], labels, amalgam=True)
    return shower


def get_roots(particle_ids, parents):
    """
    From a list of particle particle_idxs and a list of parent particle_idxs determin root particles
    
    A root particle is one whos parents are both from outside the particle list.

    Parameters
    ----------
    particle_ids : numpy array of ints
        The unique id of each particle
    parents : 2D numpy array of ints
        Each row contains the particle_idxs of two parents of each particle in particle_idxs
        These can be none

    Returns
    -------

    
    """
    roots = []
    for gid, parents_here in zip(particle_ids, parents):
        if not np.any([m in particle_ids for m in parents_here]):
            roots.append(gid)
    return roots


def get_showers(eventWise, exclude_pids=True):
    """
    From each root split the decendants into showers
    Each particle can only belong to a single shower.

    Parameters
    ----------
    eventWise :
        param exclude_pids: (Default value = [2212, 25, 35])
    exclude_pids :
        (Default value = True)

    Returns
    -------

    
    """
    if exclude_pids is True:
        exclude_pids = [25, 35]
        # problem, protons can actually appear later on in the shower, if they want
        mask = []
        for i, p in enumerate(eventWise.MCPID):
            if p == 2122 and len(eventWise.Parents[i]) == 0:
                mask.append(False)
            else:
                mask.append(p in exclude_pids)
        mask = [p not in exclude_pids  for p in eventWise.MCPID]
    else:
        if exclude_pids is None:
            exclude_pids = []
        mask = [p not in exclude_pids for p in eventWise.MCPID]
    particle_idxs = np.where(mask)[0] # this messes up the indexing 
    parent_ids = eventWise.Parents[mask]  # these refer to particle_idxs
    child_ids = eventWise.Children[mask]  # not neat indices
    pids = eventWise.MCPID[mask]
    # now where possible convert labels to names
    pdg = PDGNames.IDConverter()
    labels = np.array([pdg[x] for x in pids])
    # now we have values for the whole event,
    # but we want to split the event into showers
    # at start all particles are allocated to a diferent shower
    showers = []
    root_gids = get_roots(particle_idxs, parent_ids)
    list_particle_idxs = list(particle_idxs)
    for root_gid in root_gids:
        root_idx = list_particle_idxs.index(root_gid)
        shower_indices = []
        stack = [root_idx]
        while stack:
            next_idx = stack.pop()
            if next_idx in shower_indices:
                continue  # prevents looping
            shower_indices.append(next_idx)
            stack += [list_particle_idxs.index(child) for child in child_ids[next_idx]
                      if child in particle_idxs]
        assert len(set(shower_indices)) == len(shower_indices)
        new_shower = Shower(particle_idxs[shower_indices],
                            parent_ids[shower_indices].tolist(),
                            child_ids[shower_indices].tolist(),
                            labels[shower_indices])
        showers.append(new_shower)
    return showers


def event_shared_ends(eventWise, all_root_pids, shared_counts, exclude_pids=True):
    """
    

    Parameters
    ----------
    eventWise :
    shared_counts :
        param exclude_pids:  (Default value = True)
    all_root_pids :
        
    exclude_pids :
        (Default value = True)

    Returns
    -------

    
    """
    if exclude_pids is True:
        exclude_pids = [2212, 25, 35]
    elif exclude_pids is None:
        exclude_pids = []
    n_roots = len(all_root_pids)
    leaf_idxs = np.where(eventWise.Is_leaf)[0]
    # chase the leaves tii a root is found
    for leaf in leaf_idxs:
        to_check = [leaf]
        found = set()
        while to_check:
            idx = to_check.pop()
            parents = eventWise.Parents[idx]
            if len(parents) == 0:
                found.add(idx)
            else:
                for pidx in parents:
                    if eventWise.MCPID[pidx] in exclude_pids:
                        found.add(idx)
                    else:
                        to_check.append(pidx)
        if len(found) > 0:
            found = list(found)
            root_pids = {int(eventWise.MCPID[idx]) for idx in found}
            new_root_pids = [root for root in root_pids if root not in all_root_pids]
            for root in new_root_pids:
                print(f"New root {root}")
                all_root_pids.append(root)
                for i in range(n_roots):
                    shared_counts[i].append(0)
                n_roots += 1
                shared_counts.append([0 for _ in range(n_roots)])
            for i, root1 in enumerate(found):
                root1_idx = all_root_pids.index(eventWise.MCPID[root1])
                for root2 in found[i+1:]:
                    root2_idx = all_root_pids.index(eventWise.MCPID[root2])
                    shared_counts[root1_idx][root2_idx] += 1
                    shared_counts[root2_idx][root1_idx] += 1
    return all_root_pids, shared_counts


def shared_ends(eventWise):
    """
    

    Parameters
    ----------
    eventWise :
        

    Returns
    -------

    
    """
    eventWise.selected_index = None
    n_events = len(eventWise.MCPID)
    all_roots = []
    shared_counts = []
    for event_n in range(n_events):
        if event_n % 10 == 0:
            print(f"{event_n/n_events:.1%}", end='\r', flush=True)
        if os.path.exists("stop"):
            print(f"Completed event {event_n-1}")
            break
        eventWise.selected_index = event_n
        all_roots, shared_counts = event_shared_ends(eventWise, all_roots, shared_counts)
    return all_roots, shared_counts


def plot_shared_ends(eventWise=None, all_roots=None, shared_counts=None):
    """
    

    Parameters
    ----------
    eventWise :
        Default value = None)
    all_roots :
        Default value = None)
    shared_counts :
        Default value = None)

    Returns
    -------

    
    """
    if all_roots is None:
        if isinstance(eventWise, str):
            eventWise = Components.EventWise.from_file(eventWise)
        all_roots, shared_counts = shared_ends(eventWise)
    n_roots = len(all_roots)

    fig, ax = plt.subplots()
    shared_counts = np.array(shared_counts)
    im = ax.imshow(shared_counts)

    # We want to show all ticks...
    ax.set_xticks(np.arange(n_roots))
    ax.set_yticks(np.arange(n_roots))
    # ... and label them with the respective list entries
    ax.set_xticklabels(all_roots)
    ax.set_yticklabels(all_roots)

    # Rotate the tick labels and set their alignment.
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right",
             rotation_mode="anchor")

    # Loop over data dimensions and create text annotations.
    for i in range(n_roots):
        for j in range(n_roots):
            text = ax.text(j, i, f"{shared_counts[i, j]:g}",
                           ha="center", va="center", color="w")
    ax.set_title("Counts of end state particles shared between showers by sharing shower root.")
    fig.tight_layout()
    plt.show()
    return all_roots, shared_counts


if __name__ == '__main__':
    #plot_shared_ends("megaIgnore/basis_2k.awkd")
    pass
