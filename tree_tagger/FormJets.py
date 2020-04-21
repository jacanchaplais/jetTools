import numpy as np
import scipy
import scipy.spatial
import awkward
import subprocess
import os
import csv
from matplotlib import pyplot as plt
from ipdb import set_trace as st
from skhep import math as hepmath
from tree_tagger import Components, TrueTag, InputTools


class PseudoJet:
    """ """
    int_columns = ["Pseudojet_InputIdx",
                   "Pseudojet_Parent", "Pseudojet_Child1", "Pseudojet_Child2",
                   "Pseudojet_Rank"]
    float_columns = ["Pseudojet_PT",
                     "Pseudojet_Rapidity",
                     "Pseudojet_Phi",
                     "Pseudojet_Energy",
                     "Pseudojet_Px",
                     "Pseudojet_Py",
                     "Pseudojet_Pz",
                     "Pseudojet_JoinDistance"]
    def __init__(self, eventWise, selected_index=None, jet_name='PseudoJet', from_PseudoRapidity=False,
                 ints_floats=None, **kwargs):
        #print('init_psu', end='\r', flush=True)
        # jets can have a varient name
        # this allows multiple saves in the same file
        self.jet_name = jet_name
        self.jet_parameters = {}
        dict_jet_params = kwargs.get('dict_jet_params', {})
        for key in dict_jet_params:  # create the formatting of a eventWise column
            key = key.replace(' ', '')
            key = key[0].upper() + key[1:]
            self.jet_parameters[key] = dict_jet_params[key]
        self.int_columns = [c.replace('Pseudojet', self.jet_name) for c in self.int_columns]
        self.float_columns = [c.replace('Pseudojet', self.jet_name) for c in self.float_columns]
        self.from_PseudoRapidity = from_PseudoRapidity
        if self.from_PseudoRapidity:
            idx = next(i for i, c in enumerate(self.float_columns) if c.endswith("_Rapidity"))
            self.float_columns[idx] = self.float_columns[idx].replace("_Rapidity", "_PseudoRapidity")
        # make a table of ints and a table of floats
        # lists not arrays, becuase they will grow
        self._set_column_numbers()
        if isinstance(eventWise, str):
            assert selected_index is not None, "If loading eventWise form file must specify and index"
            self.eventWise = Components.EventWise.from_file(eventWise)
        else:
            self.eventWise = eventWise
        if selected_index is not None:
            self.eventWise.selected_index = selected_index
        assert self.eventWise.selected_index is not None, "Must specify an index (event number) for the eventWise"
        if ints_floats is not None:
            assert len(ints_floats) == 2
            self._ints = ints_floats[0]
            self._floats = ints_floats[1]
            if isinstance(self._ints, np.ndarray):
                # these are forced into list format
                self._ints = self._ints.tolist()
                self._floats = self._floats.tolist()
            self.root_jetInputIdxs = kwargs.get('root_jetInputIdxs', [])
        else:
            assert "JetInputs_PT" in eventWise.columns, "eventWise must have JetInputs"
            assert isinstance(eventWise.selected_index, int), "selected index should be int"
            
            self.n_inputs = len(eventWise.JetInputs_PT)
            self._ints = [[i, -1, -1, -1, -1] for i in range(self.n_inputs)]
            if self.from_PseudoRapidity:
                rapidity_var = eventWise.JetInputs_PseudoRapidity
            else:
                rapidity_var = eventWise.JetInputs_Rapidity
            self._floats = np.hstack((eventWise.JetInputs_PT.reshape((-1, 1)),
                                      rapidity_var.reshape((-1, 1)),
                                      eventWise.JetInputs_Phi.reshape((-1, 1)),
                                      eventWise.JetInputs_Energy.reshape((-1, 1)),
                                      eventWise.JetInputs_Px.reshape((-1, 1)),
                                      eventWise.JetInputs_Py.reshape((-1, 1)),
                                      eventWise.JetInputs_Pz.reshape((-1, 1)),
                                      np.zeros((self.n_inputs, 1)))).tolist()
            # as we go note the root notes of the pseudojets
            self.root_jetInputIdxs = []
        # define the physical distance measure
        # this requires that the class has had the attribute self.Invarient
        # set which should be done by the class that inherits from this one before calling this constructor
        self._define_physical_distance()
        # keep track of how many clusters don't yet have a parent
        self._calculate_currently_avalible()
        self._distances2 = None
        self._calculate_distances()
        if kwargs.get("assign", False):
            self.assign_parents()

    def _define_physical_distance(self):
        """ """
        pt_col  = self._PT_col 
        exponent_now = self.PTExponentPosition == 'input'
        exponent = self.ExponentMultiplier * 2
        deltaR2 = self.DeltaR**2
        # same for everything but Luclus
        if exponent_now:
            def beam_distance2(row):
                return deltaR2 * row[pt_col]**exponent
        else:
            def beam_distance2(row):
                return deltaR2
        if self.Invarient == "Luclus":
            rap_col = self._Rapidity_col
            phi_col = self._Phi_col
            def physical_distance2(row, column):
                """
                

                Parameters
                ----------
                row :
                    param column:
                column :
                    

                Returns
                -------

                """
                angular_distance = Components.angular_distance(row[phi_col], column[phi_col])
                distance2 = (row[rap_col] - column[rap_col])**2 + angular_distance**2
                if exponent_now:
                    distance2 *= (row[pt_col]**exponent)* (column[pt_col]**exponent) *\
                                 (row[pt_col] + column[pt_col])**-exponent
                return distance2
            def beam_distance2(_):
                return deltaR2
        elif self.Invarient == 'invarient':
            px_col = self._Px_col 
            py_col = self._Py_col 
            pz_col = self._Pz_col 
            e_col = self._Energy_col
            def physical_distance2(row, column):
                """
                

                Parameters
                ----------
                row :
                    param column:
                column :
                    

                Returns
                -------

                """
                distance2 = (row[e_col]*column[e_col]
                             - row[px_col]*column[px_col]
                             - row[py_col]*column[py_col]
                             - row[pz_col]*column[pz_col])
                if exponent_now:
                    distance2 *= min(row[pt_col]**exponent, column[pt_col]**exponent)
                return distance2
        elif self.Invarient == 'normed':
            px_col  = self._Px_col 
            py_col  = self._Py_col 
            pz_col  = self._Pz_col 
            e_col = self._Energy_col
            small_num = 1e-10
            def physical_distance2(row, column):
                """
                

                Parameters
                ----------
                row :
                    param column:
                column :
                    

                Returns
                -------

                """
                energies = row[e_col] * column[e_col]
                if energies == 0:
                    energies = small_num
                row_3vec = np.array([row[px_col], row[py_col], row[pz_col]])
                column_3vec = np.array([column[px_col], column[py_col], column[pz_col]])
                distance2 = 1. - np.sum(row_3vec*column_3vec)/energies
                if exponent_now:
                    distance2 *= min(row[pt_col]**exponent, column[pt_col]**exponent)
                return distance2
        elif self.Invarient == 'angular':
            rap_col = self._Rapidity_col
            phi_col = self._Phi_col
            def physical_distance2(row, column):
                """
                

                Parameters
                ----------
                row :
                    param column:
                column :
                    

                Returns
                -------

                """
                angular_distance = Components.angular_distance(row[phi_col], column[phi_col])
                distance2 = (row[rap_col] - column[rap_col])**2 + angular_distance**2
                if exponent_now:
                    distance2 *= min(row[pt_col]**exponent, column[pt_col]**exponent)
                return distance2
        else:
            raise ValueError(f"Don't recognise {self.Invarient} as an Invarient")
        self.physical_distance2 = physical_distance2
        self.beam_distance2 = beam_distance2

    def _set_hyperparams(self, param_list, dict_jet_params, kwargs):
        """
        

        Parameters
        ----------
        param_list :
            param dict_jet_params:
        kwargs :
            
        dict_jet_params :
            

        Returns
        -------

        """
        #print('hpar_psu', end='\r', flush=True)
        if dict_jet_params is None:
            dict_jet_params = {}
        stripped_params = {name.split("_")[-1]:name for name in dict_jet_params}
        for name in param_list:
            if name in stripped_params:
                assert name not in kwargs
                setattr(self, name, dict_jet_params[stripped_params[name]])
            elif name in kwargs:
                setattr(self, name, kwargs[name])
                dict_jet_params[name] = kwargs[name]
                del kwargs[name]
            else:
                setattr(self, name, param_list[name])
                dict_jet_params[name] = param_list[name]
        kwargs['dict_jet_params'] = dict_jet_params

    def _set_column_numbers(self):
        """ """
        #print('coln_psu', end='\r', flush=True)
        prefix_len = len(self.jet_name) + 1
        # int columns
        self._int_contents = {}
        for i, name in enumerate(self.int_columns):
            attr_name = '_' + name[prefix_len:] + "_col"
            self._int_contents[name[prefix_len:]] = attr_name
            setattr(self, attr_name, i)
        # float columns
        self._float_contents = {}
        for i, name in enumerate(self.float_columns):
            if "PseudoRapidity" == name[prefix_len:]:
                name = "Rapidity"
            attr_name = '_' + name[prefix_len:] + "_col"
            self._float_contents[name[prefix_len:]] = attr_name
            setattr(self, attr_name, i)

    def __dir__(self):
        new_attrs = set(super().__dir__())
        return sorted(new_attrs)

    def _calculate_currently_avalible(self):
        """ """
        #print('cavl_psu', end='\r', flush=True)
        # keep track of how many clusters don't yet have a parent
        self.currently_avalible = sum([p[self._Parent_col]==-1 for p in self._ints])

    def __getattr__(self, attr_name):
        """ the float columns form whole jet attrs"""
        # capitalise raises the case of the first letter
        attr_name = attr_name[0].upper() + attr_name[1:]
        if attr_name in self._float_contents:
            if len(self) == 0:  # if there are no pesudojets, there are no contents
                return np.nan
            # floats return the value of the root
            # or list if more than one root
            col_num = getattr(self, self._float_contents[attr_name])
            values = np.array([floats[col_num] for floats, ints in zip(self._floats, self._ints)
                               if ints[self._Parent_col] == -1])
            if attr_name == 'Phi':  # make sure it's -pi to pi
                values = Components.confine_angle(values)
            if len(values) == 0:
                return 0.
            if len(values) == 1:
                return values[0]
            return values
        elif attr_name in self._int_contents:
            # ints return every value
            col_num = getattr(self, self._int_contents[attr_name])
            return np.array([ints[col_num] for ints in self._ints])
        elif attr_name == "Rapidity":
            # if the jet was constructed with pseudorapidity we might still want to know the rapidity
            return Components.ptpze_to_rapidity(self.PT, self.Pz, self.Energy)
        elif attr_name =="Pseudorapidity":
            # vice verca
            return Components.theta_to_pseudorapidity(self.Theta)
        raise AttributeError(f"{self.__class__.__name__} does not have {attr_name}")

    @property
    def P(self):
        """ """
        if len(self) == 0:
            return np.nan
        return np.linalg.norm([self.Px, self.Py, self.Pz])

    @property
    def Theta(self):
        """ """
        if len(self) == 0:
            return np.nan
        theta = Components.ptpz_to_theta(self.PT, self.Pz)
        return theta

    @classmethod
    def create_updated_dict(cls, pseudojets, jet_name, event_index, eventWise=None, arrays=None):
        """
        Make the dictionary to be appended to an eventWise for writing

        Parameters
        ----------
        pseudojets :
            param jet_name:
        event_index :
            param eventWise: (Default value = None)
        arrays :
            Default value = None)
        jet_name :
            
        eventWise :
             (Default value = None)

        Returns
        -------

        """
        #print('udic_psu', end='\r', flush=True)
        if arrays is None:
            save_columns = [jet_name + "_RootInputIdx"]
            int_columns = [c.replace('Pseudojet', jet_name) for c in cls.int_columns]
            float_columns = [c.replace('Pseudojet', jet_name) for c in cls.float_columns]
            save_columns += float_columns
            save_columns += int_columns
            eventWise.selected_index = None
            arrays = {name: list(getattr(eventWise, name, [])) for name in save_columns}
        # check there are enough event rows
        for name in arrays:
            while len(arrays[name]) <= event_index:
                arrays[name].append([])
        for jet in pseudojets:
            assert jet.eventWise == pseudojets[0].eventWise
            arrays[jet_name + "_RootInputIdx"][event_index].append(awkward.fromiter(jet.root_jetInputIdxs))
            # if an array is deep it needs converting to an awkward array
            ints = awkward.fromiter(jet._ints)
            for col_num, name in enumerate(jet.int_columns):
                arrays[name][event_index].append(ints[:, col_num])
            floats = awkward.fromiter(jet._floats)
            for col_num, name in enumerate(jet.float_columns):
                arrays[name][event_index].append(floats[:, col_num])
        return arrays

    def create_param_dict(self):
        """ """
        #print('pdic_psu', end='\r', flush=True)
        jet_name = self.jet_name
        # add any default values
        defaults = {name:value for name, value in self.param_list.items()
                    if name not in self.jet_parameters}
        params = {**self.jet_parameters, **defaults}
        return params

    @classmethod
    def write_event(cls, pseudojets, jet_name="Pseudojet", event_index=None, eventWise=None):
        """
        Save a handful of jets together

        Parameters
        ----------
        pseudojets :
            param jet_name: (Default value = "Pseudojet")
        event_index :
            Default value = None)
        eventWise :
            Default value = None)
        jet_name :
             (Default value = "Pseudojet")

        Returns
        -------

        """
        #print('wevt_psu', end='\r', flush=True)
        if eventWise is None:
            eventWise = pseudojets[0].eventWise
        # only need to check the parameters of one jet (adds the hyperparameters)
        pseudojets[0].check_params(eventWise)
        if event_index is None:
            event_index = eventWise.selected_index
        arrays = cls.create_updated_dict(pseudojets, jet_name, event_index, eventWise)
        arrays = {name: awkward.fromiter(arrays[name]) for name in arrays}
        eventWise.append(**arrays)

    def check_params(self, eventWise):
        """
        if the  eventWise contains params, verify they are the same, else write them

        Parameters
        ----------
        eventWise :
            

        Returns
        -------

        """
        #print('ckpr_psu', end='\r', flush=True)
        my_params = self.create_param_dict()
        written_params = get_jet_params(eventWise, self.jet_name)
        if written_params:  # if written params exist check they match the jets params
            # returning false imediatly if not
            if set(written_params.keys()) != set(my_params.keys()):
                return False
            for name in written_params:
                try:
                    same = np.allclose(written_params[name], my_params[name])
                    if not same:
                        return False
                except TypeError:
                    if written_params[name] != my_params[name]:
                        return False
        else:  # save the jets params
            new_hyper = {self.jet_name + '_' + name: my_params[name] for name in my_params}
            eventWise.append_hyperparameters(**new_hyper)
        # if we get here everything went well
        return True

    @classmethod
    def multi_from_file(cls, file_name, event_idx, jet_name="Pseudojet", batch_start=None, batch_end=None):
        """
        read a handful of jets from file

        Parameters
        ----------
        file_name :
            param event_idx:
        jet_name :
            Default value = "Pseudojet")
        batch_start :
            Default value = None)
        batch_end :
            Default value = None)
        event_idx :
            

        Returns
        -------

        """
        int_columns = [c.replace('Pseudojet', jet_name) for c in cls.int_columns]
        float_columns = [c.replace('Pseudojet', jet_name) for c in cls.float_columns]
        # could write a version that just read one jet if needed
        eventWise = Components.EventWise.from_file(file_name)
        eventWise.selected_index = event_idx
        # check if its a pseudorapidty jet
        if jet_name + "_Rapidity" not in eventWise.columns:
            assert jet_name + "_PseudoRapidity" in eventWise.columns
            idx = float_columns.index(jet_name + "_Rapidity")
            float_columns[idx] = float_columns[idx].replace("_Rapidity", "_PseudoRapidity")
        save_name = eventWise.save_name
        dir_name = eventWise.dir_name
        avalible = len(getattr(eventWise, int_columns[0]))
        # decide on the start and stop points
        if batch_start is None:
            batch_start = 0
        if batch_end is None:
            batch_end = avalible
        elif batch_end > avalible:
            batch_end = avalible
        # get from the file
        jets = []
        param_columns = [c for c in eventWise.hyperparameter_columns if c.startswith(jet_name)]
        param_dict = {name: getattr(eventWise, name) for name in param_columns}
        for i in range(batch_start, batch_end):
            roots = getattr(eventWise, jet_name + "_RootInputIdx")[i]
            # need to reassemble to ints and the floats
            int_values = []
            for name in int_columns:
                int_values.append(np.array(getattr(eventWise, name)[i]).reshape((-1, 1)))
            ints = np.hstack(int_values)
            float_values = []
            for name in float_columns:
                float_values.append(np.array(getattr(eventWise, name)[i]).reshape((-1, 1)))
            floats = np.hstack(float_values)
            new_jet = cls(eventWise=file_name,
                          selected_index=i,
                          ints_floats=(ints.tolist(), floats.tolist()),
                          root_jetInputIdxs=roots,
                          dict_jet_params=param_dict)
            new_jet.currently_avalible = 0  # assumed since we are reading from file
            jets.append(new_jet)
        return jets

    def _calculate_roots(self):
        """ """
        #print('crot_psu', end='\r', flush=True)
        self.root_jetInputIdxs = []
        # should only bee needed for reading from file self.currently_avalible == 0, "Assign parents before you calculate roots"
        pseudojet_ids = self.InputIdx
        parent_ids = self.Parent
        for mid, pid in zip(parent_ids, pseudojet_ids):
            if (mid == -1 or
                mid not in pseudojet_ids or
                mid == pid):
                self.root_jetInputIdxs.append(pid)

    def split(self):
        """ """
        assert self.currently_avalible == 0, "Need to assign_parents before splitting"
        if len(self) == 0:
            return []
        self.JetList = []
        # ensure the split has the same order every time
        self.root_jetInputIdxs = sorted(self.root_jetInputIdxs)
        for root in self.root_jetInputIdxs:
            group = self.get_decendants(lastOnly=False, jetInputIdx=root)
            group_idx = [self.idx_from_inpIdx(ID) for ID in group]
            ints = [self._ints[i] for i in group_idx]
            floats = [self._floats[i] for i in group_idx]
            jet = type(self)(ints_floats=(ints, floats),
                             jet_name=self.jet_name,
                             selected_index=self.eventWise.selected_index,
                             eventWise=self.eventWise,
                             dict_jet_params=self.jet_parameters)
            jet.currently_avalible = 0
            jet.root_jetInputIdxs = [root]
            self.JetList.append(jet)
        return self.JetList
    
    def _calculate_distances(self):
        """ """
        # this is caluculating all the distances
        raise NotImplementedError

    def _recalculate_one(self, remove_index, replace_index):
        """
        

        Parameters
        ----------
        remove_index :
            param replace_index:
        replace_index :
            

        Returns
        -------

        """
        raise NotImplementedError

    def _merge_pseudojets(self, pseudojet_index1, pseudojet_index2, distance2):
        """
        

        Parameters
        ----------
        pseudojet_index1 :
            param pseudojet_index2:
        distance2 :
            
        pseudojet_index2 :
            

        Returns
        -------

        """
        replace_index, remove_index = sorted([pseudojet_index1, pseudojet_index2])
        new_pseudojet_ints, new_pseudojet_floats = self._combine(remove_index, replace_index, distance2)
        # move the first pseudojet to the back without replacement
        pseudojet1_ints = self._ints.pop(remove_index)
        pseudojet1_floats = self._floats.pop(remove_index)
        self._ints.append(pseudojet1_ints)
        self._floats.append(pseudojet1_floats)
        # move the second pseudojet to the back but replace it with the new pseudojet
        pseudojet2_ints = self._ints[replace_index]
        pseudojet2_floats = self._floats[replace_index]
        self._ints.append(pseudojet2_ints)
        self._floats.append(pseudojet2_floats)
        self._ints[replace_index] = new_pseudojet_ints
        self._floats[replace_index] = new_pseudojet_floats
        # one less pseudojet avalible
        self.currently_avalible -= 1
        # now recalculate for the new pseudojet
        self._recalculate_one(remove_index, replace_index)

    def _remove_pseudojet(self, pseudojet_index):
        """
        

        Parameters
        ----------
        pseudojet_index :
            

        Returns
        -------

        """
        # move the first pseudojet to the back without replacement
        pseudojet_ints = self._ints.pop(pseudojet_index)
        pseudojet_floats = self._floats.pop(pseudojet_index)
        self._ints.append(pseudojet_ints)
        self._floats.append(pseudojet_floats)
        self.root_jetInputIdxs.append(pseudojet_ints[self._InputIdx_col])
        # delete the row and column
        self._distances2 = np.delete(self._distances2, (pseudojet_index), axis=0)
        self._distances2 = np.delete(self._distances2, (pseudojet_index), axis=1)
        # one less pseudojet avalible
        self.currently_avalible -= 1
        
    def assign_parents(self):
        """ """
        #print('asign_psu', end='\r', flush=True)
        while self.currently_avalible > 0:
            # now find the smallest distance
            row, column = np.unravel_index(np.argmin(self._distances2), self._distances2.shape)
            if row == column:
                self._remove_pseudojet(row)
            else:
                self._merge_pseudojets(row, column, self._distances2[row, column])

    def plt_assign_parents(self):
        """ """
        # dendogram < this should be
        plt.axis([-5, 5, -np.pi-0.5, np.pi+0.5])
        inv_pts = [1/p[self._PT_col]**2 for p in self._floats]
        plt.scatter(self.Rapidity, self.Phi, inv_pts, c='w')
        plt.rc('text', usetex=True)
        plt.rc('font', family='serif')
        plt.ylabel(r"$\phi$ - barrel angle")
        if self.from_PseudoRapidity:
            plt.xlabel(r"$\eta$ - pseudo rapidity")
        else:
            plt.xlabel(r"Rapidity")
        plt.title("Detected Hits")
        plt.gca().set_facecolor('gray')
        # for getting rid of the axis
        #plt.gca().get_xaxis().set_visible(False)
        #plt.gca().get_yaxis().set_visible(False)
        #plt.gca().spines['top'].set_visible(False)
        #plt.gca().spines['right'].set_visible(False)
        #plt.gca().spines['bottom'].set_visible(False)
        #plt.gca().spines['left'].set_visible(False)
        plt.pause(0.05)#
        input("Press enter to start pseudojeting")
        while self.currently_avalible > 0:
            # now find the smallest distance
            row, column = np.unravel_index(np.argmin(self._distances2), self._distances2.shape)
            if row == column:
                decendents = self.get_decendants(lastOnly=True, pseudojet_idx=row)
                decendents_idx = [self.idx_from_inpIdx(d) for d in decendents]
                draps = [self._floats[d][self._Rapidity_col] for d in decendents_idx]
                dphis = [self._floats[d][self._Phi_col] for d in decendents_idx]
                des = [self._floats[d][self._Energy_col] for d in decendents_idx]
                dpts = [1/self._floats[d][self._PT_col]**2 for d in decendents_idx]  # WHY??
                plt.scatter(draps, dphis, dpts, marker='D')
                print(f"Added jet of {len(decendents)} tracks, {self.currently_avalible} pseudojets unfinished")
                plt.pause(0.05)
                input("Press enter for next pseudojet")
                self._remove_pseudojet(row)
            else:
                self._merge_pseudojets(row, column, self._distances2[row, column])
        plt.show()

    def idx_from_inpIdx(self, jetInputIdx):
        """
        

        Parameters
        ----------
        jetInputIdx :
            

        Returns
        -------

        """
        ids = [p[self._InputIdx_col] for p in self._ints]
        pseudojet_idx = next((idx for idx, inp_idx in enumerate(ids)
                              if inp_idx == jetInputIdx),
                             None)
        if pseudojet_idx is not None:
            return pseudojet_idx
        raise ValueError(f"No pseudojet with ID {jetInputIdx}")

    def get_decendants(self, lastOnly=True, jetInputIdx=None, pseudojet_idx=None):
        """
        

        Parameters
        ----------
        lastOnly :
            Default value = True)
        jetInputIdx :
            Default value = None)
        pseudojet_idx :
            Default value = None)

        Returns
        -------

        """
        #print('gdec_psu', end='\r', flush=True)
        if jetInputIdx is None and pseudojet_idx is None:
            raise TypeError("Need to specify a pseudojet")
        elif pseudojet_idx is None:
            pseudojet_idx = self.idx_from_inpIdx(jetInputIdx)
        elif jetInputIdx is None:
            jetInputIdx = self._ints[pseudojet_idx][self._InputIdx_col]
        decendents = []
        if not lastOnly:
            decendents.append(jetInputIdx)
        # make local variables for speed
        local_obs = self.local_obs_idx()
        child1_col = self._Child1_col
        child2_col = self._Child2_col
        # bu this point we have the first pseudojet
        if pseudojet_idx in local_obs:
            # just the one
            return [jetInputIdx]
        to_check = []
        ignore = []
        d1 = self._ints[pseudojet_idx][child1_col]
        d2 = self._ints[pseudojet_idx][child2_col]
        if d1 >= 0:
            to_check.append(d1)
        if d2 >= 0:
            to_check.append(d2)
        while len(to_check) > 0:
            jetInputIdx = to_check.pop()
            pseudojet_idx = self.idx_from_inpIdx(jetInputIdx)
            if (pseudojet_idx in local_obs or not lastOnly):
                decendents.append(jetInputIdx)
            else:
                ignore.append(jetInputIdx)
            d1 = self._ints[pseudojet_idx][child1_col]
            d2 = self._ints[pseudojet_idx][child2_col]
            if d1 >= 0 and d1 not in (decendents + ignore):
                to_check.append(d1)
            if d2 >= 0 and d2 not in (decendents + ignore):
                to_check.append(d2)
        return decendents

    def local_obs_idx(self):
        """ """
        idx_are_obs = [i for i in range(len(self)) if
                       (self._ints[i][self._Child1_col] < 0 and
                       self._ints[i][self._Child2_col] < 0)]
        return idx_are_obs

    def _combine(self, pseudojet_index1, pseudojet_index2, distance2):
        """
        

        Parameters
        ----------
        pseudojet_index1 :
            param pseudojet_index2:
        distance2 :
            
        pseudojet_index2 :
            

        Returns
        -------

        """
        #print('comb_psu', end='\r', flush=True)
        new_id = max([ints[self._InputIdx_col] for ints in self._ints]) + 1
        self._ints[pseudojet_index1][self._Parent_col] = new_id
        self._ints[pseudojet_index2][self._Parent_col] = new_id
        rank = max(self._ints[pseudojet_index1][self._Rank_col],
                   self._ints[pseudojet_index2][self._Rank_col]) + 1
        # inputidx, parent, child1, child2 rank
        # child1 shoul
        ints = [new_id,
                -1,
                self._ints[pseudojet_index1][self._InputIdx_col],
                self._ints[pseudojet_index2][self._InputIdx_col],
                rank]
        # PT px py pz eta phi energy join_distance
        # it's easier conceptually to calculate pt, phi and rapidity afresh than derive them
        # from the exisiting pt, phis and rapidity
        floats = [f1 + f2 for f1, f2 in
                  zip(self._floats[pseudojet_index1],
                      self._floats[pseudojet_index2])]
        px = floats[self._Px_col]
        py = floats[self._Py_col]
        pz = floats[self._Pz_col]
        energy = floats[self._Energy_col]
        phi, pt = Components.pxpy_to_phipt(px, py)
        floats[self._PT_col] = pt
        floats[self._Phi_col] = phi
        if self.from_PseudoRapidity:
            theta = Components.ptpz_to_theta(pt, pz)
            floats[self._Rapidity_col] = Components.theta_to_pseudorapidity(theta)
        else:
            floats[self._Rapidity_col] = Components.ptpze_to_rapidity(pt, pz, energy)
        # fix the distance
        floats[self._JoinDistance_col] = np.sqrt(distance2)
        return ints, floats

    def __len__(self):
        return len(self._ints)

    def __eq__(self, other):
        if len(self) != len(other):
            return False 
        ints_eq = self._ints == other._ints
        floats_eq = np.allclose(self._floats, other._floats)
        return ints_eq and floats_eq


class Traditional(PseudoJet):
    """ """
    param_list = {'DeltaR': None, 'ExponentMultiplier': None, 'Invarient': 'angular'}
    def __init__(self, eventWise=None, dict_jet_params=None, **kwargs):
        self._set_hyperparams(self.param_list, dict_jet_params, kwargs)
        self.PTExponentPosition = 'input'
        super().__init__(eventWise, **kwargs)

    def _calculate_distances(self):
        """ """
        # this is caluculating all the distances
        self._distances2 = np.full((self.currently_avalible, self.currently_avalible), np.inf)
        # for speed, make local variables
        pt_col  = self._PT_col 
        exponent = self.ExponentMultiplier * 2
        DeltaR2 = self.DeltaR**2
        for row in range(self.currently_avalible):
            for column in range(self.currently_avalible):
                if column > row:
                    continue  # we only need a triangular matrix due to symmetry
                elif self._floats[row][pt_col] == 0:
                    distance2 = 0  # soft radation might as well be at 0 distance
                elif column == row:
                    distance2 = self._floats[row][pt_col]**exponent * DeltaR2
                else:
                    distance2 = self.physical_distance2(self._floats[row], self._floats[column])
                self._distances2[row, column] = distance2

    def _recalculate_one(self, remove_index, replace_index):
        """
        

        Parameters
        ----------
        remove_index :
            param replace_index:
        replace_index :
            

        Returns
        -------

        """
        # delete the larger index keep the smaller index
        assert remove_index > replace_index
        # delete the first row and column of the merge
        self._distances2 = np.delete(self._distances2, (remove_index), axis=0)
        self._distances2 = np.delete(self._distances2, (remove_index), axis=1)

        # calculate new values into the second column
        for row in range(self.currently_avalible):
            column = replace_index
            if column > row:
                distance2 = self._distances2[column, row]
            if column == row:
                distance2 = self.beam_distance2(self._floats[row][self._PT_col])
            else:
                distance2 = self.physical_distance2(self._floats[row], self._floats[column])
            self._distances2[row, column] = distance2

    @classmethod
    def read_fastjet(cls, arg, eventWise, jet_name="FastJet", do_checks=False):
        """
        

        Parameters
        ----------
        arg :
            param eventWise:
        jet_name :
            Default value = "FastJet")
        do_checks :
            Default value = False)
        eventWise :
            

        Returns
        -------

        """
        #  fastjet format
        assert eventWise.selected_index is not None
        if isinstance(arg, str):
            ifile_name = os.path.join(arg, f"fastjet_ints.csv")
            ffile_name = os.path.join(arg, f"fastjet_doubles.csv")
            # while it would be nice to filter warnings here it's a high frequency bit of code
            # and I don't want a speed penalty here
            fast_ints = np.genfromtxt(ifile_name, skip_header=1, dtype=int)
            fast_floats = np.genfromtxt(ffile_name, skip_header=1)
            with open(ifile_name, 'r') as ifile:
                header = ifile.readline()[1:]
            with open(ffile_name, 'r') as ffile:
                fcolumns = ffile.readline()[1:].split()
        else:
            header = arg[0].decode()[1:]
            arrays = [[]]
            a_type = int
            for line in arg[1:]:
                line = line.decode().strip()
                if line[0] == '#':  # moves from the ints to the doubles
                    arrays.append([])
                    a_type = float
                    fcolumns = line[1:].split()
                else:
                    arrays[-1].append([a_type(x) for x in line.split()])
            assert len(arrays) == 2, f"Problem wiht input; \n{arg}"
            fast_ints = np.array(arrays[0], dtype=int)
            fast_floats = np.array(arrays[1], dtype=float)
        # first line will be the tech specs and columns
        header = header.split()
        DeltaR = float(header[0].split('=')[1])
        algorithm_name = header[1]
        if algorithm_name == 'kt_algorithm':
            ExponentMultiplier = 1
        elif algorithm_name == 'cambridge_algorithm':
            ExponentMultiplier = 0
        elif algorithm_name == 'antikt_algorithm':
            ExponentMultiplier = -1
        else:
            raise ValueError(f"Algorithm {algorithm_name} not recognised")
        # get the colums for the header
        icolumns = {name: i for i, name in enumerate(header[header.index("Columns;") + 1:])}
        # and from this get the columns
        # the file of fast_ints contains
        n_fastjet_int_cols = len(icolumns)
        if len(fast_ints.shape) == 1:
            fast_ints = fast_ints.reshape((-1, n_fastjet_int_cols))
        else:
            assert fast_ints.shape[1] == n_fastjet_int_cols
        # check that all the input idx have come through
        n_inputs = len(eventWise.JetInputs_SourceIdx)
        assert set(np.arange(n_inputs)).issubset(set(fast_ints[:, icolumns["InputIdx"]])), "Problem with inpu idx"
        next_free = np.max(fast_ints[:, icolumns["InputIdx"]], initial=-1) + 1
        fast_idx_dict = {}
        for line_idx, i in fast_ints[:, [icolumns["pseudojet_id"], icolumns["InputIdx"]]]:
            if i == -1:
                fast_idx_dict[line_idx] = next_free
                next_free += 1
            else:
                fast_idx_dict[line_idx] = i
        fast_idx_dict[-1]=-1
        fast_ints = np.vectorize(fast_idx_dict.__getitem__,
                                 otypes=[np.float])(fast_ints[:, [icolumns["pseudojet_id"],
                                                                  icolumns["parent_id"],
                                                                  icolumns["child1_id"],
                                                                  icolumns["child2_id"]]])
        # now the Inputidx is the first one and the pseudojet_id can be removed
        del icolumns["pseudojet_id"]
        icolumns = {name: i-1 for name, i in icolumns.items()}
        n_fastjet_float_cols = len(fcolumns)
        if do_checks:
            # check that the parent child relationship is reflexive
            for line in fast_ints:
                identifier = f"pseudojet inputIdx={line[0]} "
                if line[icolumns["child1_id"]] == -1:
                    assert line[icolumns["child2_id"]] == -1, identifier + "has only one child"
                else:
                    assert line[icolumns["child1_id"]] != line[icolumns["child2_id"]], identifier + " child1 and child2 are same"
                    child1_line = fast_ints[fast_ints[:, icolumns["InputIdx"]]
                                            == line[icolumns["child1_id"]]][0]
                    assert child1_line[1] == line[0], identifier + " first child dosn't acknowledge parent"
                    child2_line = fast_ints[fast_ints[:, icolumns["InputIdx"]]
                                            == line[icolumns["child2_id"]]][0]
                    assert child2_line[1] == line[0], identifier + " second child dosn't acknowledge parent"
                if line[1] != -1:
                    assert line[icolumns["InputIdx"]] != line[icolumns["parent_id"]], identifier + "is it's own mother"
                    parent_line = fast_ints[fast_ints[:, icolumns["InputIdx"]]
                                            == line[icolumns["parent_id"]]][0]
                    assert line[0] in parent_line[[icolumns["child1_id"],
                                                   icolumns["child2_id"]]], identifier + " parent doesn't acknowledge child"
            for fcol, expected in zip(fcolumns, PseudoJet.float_columns):
                assert expected.endswith(fcol)
            if len(fast_ints) == 0:
                assert len(fast_floats) == 0, "No ints found, but floats are present!"
                print("Warning, no values from fastjet.")
        if len(fast_floats.shape) == 1:
            fast_floats = fast_floats.reshape((-1, n_fastjet_float_cols))
        else:
            assert fast_floats.shape[1] == n_fastjet_float_cols
        if len(fast_ints.shape) > 1:
            num_rows = fast_ints.shape[0]
            assert len(fast_ints) == len(fast_floats), f"len({ifile_name}) != len({ffile_name})"
        elif len(fast_ints) > 0:
            num_rows = 1
        else:
            num_rows = 0
        ints = np.full((num_rows, len(cls.int_columns)), -1, dtype=int)
        floats = np.zeros((num_rows, len(cls.float_columns)), dtype=float)
        if len(fast_ints) > 0:
            ints[:, :4] = fast_ints
            floats[:, :7] = fast_floats
        # make ranks
        rank = -1
        rank_col = len(icolumns)
        ints[ints[:, icolumns["child1_id"]] == -1, rank_col] = rank
        # parents of the lowest rank is the next rank
        this_rank = set(ints[ints[:, icolumns["child1_id"]] == -1, icolumns["parent_id"]])
        this_rank.discard(-1)
        while len(this_rank) > 0:
            rank += 1
            next_rank = []
            for i in this_rank:
                ints[ints[:, icolumns["InputIdx"]] == i, rank_col] = rank
                parent = ints[ints[:, icolumns["InputIdx"]] == i, icolumns["parent_id"]]
                if parent != -1 and parent not in next_rank:
                    next_rank.append(parent)
            this_rank = next_rank
        # create the pseudojet
        new_pseudojet = cls(ints_floats=(ints, floats),
                            eventWise=eventWise,
                            DeltaR=DeltaR,
                            ExponentMultiplier=ExponentMultiplier,
                            jet_name=jet_name)
        new_pseudojet.currently_avalible = 0
        new_pseudojet._calculate_roots()
        return new_pseudojet


class Spectral(PseudoJet):
    """ """
    # list the params with default values
    param_list = {'DeltaR': None, 'NumEigenvectors': np.inf,
            'PTExponentPosition': 'input', 'PTExponentMultiplier': None,
            'AffinityType': 'exponent', 'AffinityCutoff': None,
            'Laplacien': 'unnormalised',
            'Invarient': 'angular', 'StoppingCondition': 'standard'}
    def __init__(self, eventWise=None, dict_jet_params=None, **kwargs):
        self._set_hyperparams(self.param_list, dict_jet_params, kwargs)
        self._define_calculate_affinity()
        self.eigenvalues = []  # create a list to track the eigenvalues
        super().__init__(eventWise, **kwargs)

    def _calculate_distances(self):
        """ """
        # if there is a beam particle need to get the distance to the beam particle too
        n_distances = self.currently_avalible + self.beam_particle
        if n_distances < 2:
            self._distances2 = np.zeros((1, 1))
            try:
                self._eigenspace = np.zeros((1, self.NumEigenvectors))
            except (ValueError, TypeError):
                self._eigenspace = np.zeros((1, 1))
            return np.zeros(n_distances).reshape((n_distances, n_distances))
        # to start with create a 'normal' distance measure
        # this can be based on any of the three algorithms
        physical_distances2 = np.zeros((n_distances, n_distances))
        # for speed, make local variables
        pt_col  = self._PT_col 
        rap_col = self._Rapidity_col
        phi_col = self._Phi_col
        # future calculatins will depend on the starting positions
        self._starting_position = np.array([self._floats[row][:] for row
                                            in range(self.currently_avalible)])
        self.beam_particle = self.StoppingCondition == 'beamparticle'
        if self.beam_particle:
            # the beam particles dosn't have a real location,
            # but to preserve the dimensions of future calculations, add it in
            self._starting_position = np.vstack((self._starting_position,
                                                 np.ones(len(float_columns))))
            # it is added to the end so as to maintain the indices
        for row in range(self.currently_avalible):
            for column in range(self.currently_avalible):
                if column < row:
                    distance2 = physical_distances2[column, row]  # the matrix is symmetric
                elif self._floats[row][pt_col] == 0:
                    distance2 = 0  # soft radation might as well be at 0 distance
                elif column == row:
                    # not used
                    continue
                else:
                    distance2 = self.physical_distance2(self._floats[row], self._floats[column])
                physical_distances2[row, column] = distance2
        if self.beam_particle:
            # the last row and column should give the distance of each particle to the beam
            physical_distances2[-1, :] = [self.beam_distance2(row) for row in self._starting_position]
            physical_distances2[:, -1] = physical_distances2[-1, :]
        np.fill_diagonal(physical_distances2, 0.)
        # now we are in posessio of a standard distance matrix for all points,
        # we can make an affinity calculation
        affinity = self.calculate_affinity(physical_distances2)
        # a graph laplacien can be calculated
        np.fill_diagonal(affinity, 0.)  # the affinity may have problems on the diagonal
        diagonal = np.diag(np.sum(affinity, axis=1))
        if self.Laplacien == 'unnormalised':
            laplacien = diagonal - affinity
        elif self.Laplacien == 'symmetric':
            laplacien = diagonal - affinity
            self.alt_diag = np.diag(diagonal)**(-0.5)
            diag_alt_diag = np.diag(self.alt_diag)
            laplacien = np.matmul(diag_alt_diag, np.matmul(laplacien, diag_alt_diag))
        else:
            raise NotImplementedError(f"Don't have a laplacien {self.Laplacien}")
        # get the eigenvectors (we know the smallest will be identity)
        try:
            eigenvalues, eigenvectors = scipy.linalg.eigh(laplacien, eigvals=(1, self.NumEigenvectors+1))
        except (ValueError, TypeError):
            # sometimes there are fewer eigenvalues avalible
            # just take waht can be found
            eigenvalues, eigenvectors = scipy.linalg.eigh(laplacien)[1:]
        self.eigenvalues.append(eigenvalues.tolist())
        # at the start the eigenspace positions are the eigenvectors
        self._eigenspace = np.copy(eigenvectors)
        # now treating the rows of this matrix as the new points get euclidien distances
        self._distances2 = scipy.spatial.distance.squareform(
                scipy.spatial.distance.pdist(eigenvectors),
                metric='sqeuclidean')
        if self.PTExponentPosition == 'eigenspace':
            exponent = 2 * self.PTExponentMultiplier
            # if beamparticle the last entry will be nonsense, but we wont touch it anyway
            pt_fractions = np.fromiter((row[pt_col]**exponent for row in self._starting_position),
                                       dtype=float)
            for row in range(self.currently_avalible):
                for column in range(self.currently_avalible):
                    if column < row:
                        distance2 = self._distances2[column, row]  # the matrix is symmetric
                    elif column == row:
                        # not used
                        continue
                    else:
                        # at this point apply the pt factors
                        distance2 = min(pt_fractions[row], pt_fractions[column]) * self._distances2[row, column]
                    self._distances2[row, column] = distance2
            if self.beam_particle:
                self._distances2[-1, :-1] *= pt_fractions[:-1]
                self._distances2[:-1, -1] *= pt_fractions[:-1]
        # if the clustering is not going to stop at 1 we must put something in the diagonal
        if self.beam_particle:  # in he case of a beam particle we stop the clustering when our particle reaches the beam particle
            # so the diagonal should never be grouped with
            np.fill_diagonal(self._distances2, np.inf)
        else:
            # the diagonal is the stopping condition
            np.fill_diagonal(self._distances2, self.DeltaR**2)

    def _define_calculate_affinity(self):
        """ """
        if self.AffinityCutoff is not None:
            cutoff_type = self.AffinityCutoff[0]
            cutoff_param = self.AffinityCutoff[1]
            if cutoff_type == 'knn':
                if self.AffinityType == 'exponent':
                    def calculate_affinity(distances2):
                        """
                        

                        Parameters
                        ----------
                        distances2 :
                            

                        Returns
                        -------

                        """
                        affinity = np.exp(-(distances2**0.5))
                        affinity[np.argsort(distances2, axis=0) < cutoff_param] = 0
                        return affinity
                elif self.AffinityType == 'exponent2':
                    def calculate_affinity(distances2):
                        """
                        

                        Parameters
                        ----------
                        distances2 :
                            

                        Returns
                        -------

                        """
                        affinity = np.exp(-(distances2))
                        affinity[np.argsort(distances2, axis=0) < cutoff_param] = 0
                        return affinity
                elif self.AffinityType == 'linear':
                    def calculate_affinity(distances2):
                        """
                        

                        Parameters
                        ----------
                        distances2 :
                            

                        Returns
                        -------

                        """
                        affinity = -distances2**0.5
                        affinity[np.argsort(distances2, axis=0) < cutoff_param] = 0
                        return affinity
                elif self.AffinityType == 'inverse':
                    def calculate_affinity(distances2):
                        """
                        

                        Parameters
                        ----------
                        distances2 :
                            

                        Returns
                        -------

                        """
                        affinity = distances2**-0.5
                        affinity[np.argsort(distances2, axis=0) < cutoff_param] = 0
                        return affinity
                else:
                    raise ValueError(f"affinity type {self.AffinityType} unknown")
            elif cutoff_type == 'distance':
                cutoff_param2 = cutoff_param**2
                if self.AffinityType == 'exponent':
                    def calculate_affinity(distances2):
                        """
                        

                        Parameters
                        ----------
                        distances2 :
                            

                        Returns
                        -------

                        """
                        affinity = np.exp(-(distances2**0.5))
                        affinity[distances2 > cutoff_param2] = 0
                        return affinity
                elif self.AffinityType == 'exponent2':
                    def calculate_affinity(distances2):
                        """
                        

                        Parameters
                        ----------
                        distances2 :
                            

                        Returns
                        -------

                        """
                        affinity = np.exp(-(distances2))
                        affinity[distances2 > cutoff_param2] = 0
                        return affinity
                elif self.AffinityType == 'linear':
                    def calculate_affinity(distances2):
                        """
                        

                        Parameters
                        ----------
                        distances2 :
                            

                        Returns
                        -------

                        """
                        affinity = -distances2**0.5
                        affinity[distances2 > cutoff_param2] = 0
                        return affinity
                elif self.AffinityType == 'inverse':
                    def calculate_affinity(distances2):
                        """
                        

                        Parameters
                        ----------
                        distances2 :
                            

                        Returns
                        -------

                        """
                        affinity = distances2**-0.5
                        affinity[distances2 > cutoff_param2] = 0
                        return affinity
                else:
                    raise ValueError(f"affinity type {self.AffinityType} unknown")
            else:
                raise ValueError(f"cut off {cutoff_type} unknown")
        else:
            if self.AffinityType == 'exponent':
                def calculate_affinity(distances2):
                    """
                    

                    Parameters
                    ----------
                    distances2 :
                        

                    Returns
                    -------

                    """
                    affinity = np.exp(-(distances2**0.5))
                    return affinity
            elif self.AffinityType == 'exponent2':
                def calculate_affinity(distances2):
                    """
                    

                    Parameters
                    ----------
                    distances2 :
                        

                    Returns
                    -------

                    """
                    affinity = np.exp(-(distances2))
                    return affinity
            elif self.AffinityType == 'linear':
                def calculate_affinity(distances2):
                    """
                    

                    Parameters
                    ----------
                    distances2 :
                        

                    Returns
                    -------

                    """
                    affinity = -distances2**0.5
                    return affinity
            elif self.AffinityType == 'inverse':
                def calculate_affinity(distances2):
                    """
                    

                    Parameters
                    ----------
                    distances2 :
                        

                    Returns
                    -------

                    """
                    affinity = distances2**-0.5
                    return affinity
            else:
                raise ValueError(f"affinity type {self.AffinityType} unknown")
        # this is make into a class fuction becuase it will b needed elsewhere
        self.calculate_affinity = calculate_affinity

    def _remove_pseudojet(self, pseudojet_index):
        """
        

        Parameters
        ----------
        pseudojet_index :
            

        Returns
        -------

        """
        # move the first pseudojet to the back without replacement
        pseudojet_ints = self._ints.pop(pseudojet_index)
        pseudojet_floats = self._floats.pop(pseudojet_index)
        self._ints.append(pseudojet_ints)
        self._floats.append(pseudojet_floats)
        # remove from the eigenspace
        self._eigenspace = np.delete(self._eigenspace, (pseudojet_index), axis=0)
        #self._eigenspace = np.vstack((self._eigenspace[:pseudojet_index],
        #                              self._eigenspace[pseudojet_index:],
        #                              self._eigenspace[[pseudojet_index]]))
        self.root_jetInputIdxs.append(pseudojet_ints[self._InputIdx_col])
        # delete the row and column
        self._distances2 = np.delete(self._distances2, (pseudojet_index), axis=0)
        self._distances2 = np.delete(self._distances2, (pseudojet_index), axis=1)
        # one less pseudojet avalible
        self.currently_avalible -= 1
        
    def _recalculate_one(self, remove_index, replace_index):
        """
        

        Parameters
        ----------
        remove_index :
            param replace_index:
        replace_index :
            

        Returns
        -------

        """
        # delete the larger index keep the smaller index
        assert remove_index > replace_index
        # delete the first row and column of the merge
        self._distances2 = np.delete(self._distances2, (remove_index), axis=0)
        self._distances2 = np.delete(self._distances2, (remove_index), axis=1)
        # calculate the physical distance of the new point from all original points
        # floats and ints will have been updated already in _mearge_pseudojets
        new_position = self._floats[replace_index]
        # since we take rows out of the eigenspace the laplacien also needs to get corrispondingly smaller
        new_distances2 = np.fromiter((self.physical_distance2(self._floats[row], new_position) for row in range(self.currently_avalible),
                                    dtype=float)
        if self.beam_particle:
            # then add in one more index for the beam partical
            new_distances2 = np.append(new_distances2, self.beam_distance2(new_position))
        # from this get a new line of the laplacien
        new_laplacien = -self.calculate_affinity(new_distances2)
        new_laplacien[replace_index] = 0.
        new_laplacien[replace_index] = -np.sum(new_laplacien)
        if self.Laplacien == 'symmetric':
            self.alt_diag = np.delete(self.alt_diag[remove_index])
            new_alt_diag = np.sum(new_laplacien)**(-0.5)
            self.alt_diag[replace_index] = new_alt_diag
            new_laplacien = self.alt_diag * (new_laplacien * new_alt_diag)
        # CHanged -> simply delete the eigenspace line
        self._eigenspace = np.delete(self._eigenspace, remove_index, axis=0)
        # and make its position in vector space
        new_position = np.dot(self._eigenspace.T, new_laplacien)
        self._eigenspace[replace_index] = new_position
        # get the new disntance in eigenspace
        new_distances2 = np.sum((self._eigenspace - new_position)**2, axis=1)
        if self.PTExponentPosition == 'eigenspace':
            exponent = 2 * self.PTExponentMultiplier
            pt_here = self._floats[replace_index][self._PT_col]**exponent
            pt_factor = np.array([min(row[self._PT_col]**exponent, pt_here) for row in self._floats[:self.currently_avalible]),
                                    dtype=float)
            new_distances2[:self.currently_avalible] *= pt_factor
        else:
            new_distances2 = np.sum((self._eigenspace[:self.currently_avalible] - new_position)**2, axis=1)
        if self.beam_particle:
            new_distances2[replace_index] = np.inf
        else:
            new_distances2[replace_index] = self.DeltaR**2
        self._distances2[replace_index] = new_distances2

    def assign_parents(self):
        """ """
        # the beam particle won't count towards the currently avalible
        while self.currently_avalible > 0:
            beam_index = self.currently_avalible
            # now find the smallest distance
            row, column = np.unravel_index(np.argmin(self._distances2), self._distances2.shape)
            if row == column:
                if self.beam_particle:
                    raise RuntimeError("A jet with a beam particle should never have a minimal diagonal")
                self._remove_pseudojet(row)
            elif self.beam_particle and row == beam_index:
                # the column merged with the beam
                self._remove_pseudojet(column)
            elif self.beam_particle and column == beam_index:
                # the row merged with the beam
                self._remove_pseudojet(row)
            else:
                self._merge_pseudojets(row, column, self._distances2[row, column])

    def plt_assign_parents(self):
        """ """
        # dendogram < this should be
        plt.axis([-5, 5, -np.pi-0.5, np.pi+0.5])
        inv_pts = [1/p[self._PT_col]**2 for p in self._floats]
        plt.scatter(self.Rapidity, self.Phi, inv_pts, c='w')
        plt.rc('text', usetex=True)
        plt.rc('font', family='serif')
        plt.ylabel(r"$\phi$ - barrel angle")
        if self.from_PseudoRapidity:
            plt.xlabel(r"$\eta$ - pseudo rapidity")
        else:
            plt.xlabel(r"Rapidity")
        plt.title("Detected Hits")
        plt.gca().set_facecolor('gray')
        # for getting rid of the axis
        #plt.gca().get_xaxis().set_visible(False)
        #plt.gca().get_yaxis().set_visible(False)
        #plt.gca().spines['top'].set_visible(False)
        #plt.gca().spines['right'].set_visible(False)
        #plt.gca().spines['bottom'].set_visible(False)
        #plt.gca().spines['left'].set_visible(False)
        plt.pause(0.05)#
        input("Press enter to start pseudojeting")
        while self.currently_avalible > 0:
            # now find the smallest distance
            remove_row = None
            row, column = np.unravel_index(np.argmin(self._distances2), self._distances2.shape)
            beam_index = self.currently_avalible - 1
            if row == column:
                if self.beam_particle:
                    raise RuntimeError("A jet with a beam particle should never have a minimal diagonal")
                remove_row = row
            elif self.beam_particle and row == beam_index:
                # the column merged with the beam
                remove_row = column
            elif self.beam_particle and column == beam_index:
                # the row merged with the beam
                remove_row = row
            else:
                self._merge_pseudojets(row, column, self._distances2[row, column])
            if remove_row is not None:
                decendents = self.get_decendants(lastOnly=True, pseudojet_idx=row)
                decendents_idx = [self.idx_from_inpIdx(d) for d in decendents]
                draps = [self._floats[d][self._Rapidity_col] for d in decendents_idx]
                dphis = [self._floats[d][self._Phi_col] for d in decendents_idx]
                des = [self._floats[d][self._Energy_col] for d in decendents_idx]
                dpts = [1/self._floats[d][self._PT_col]**2 for d in decendents_idx]  # WHY??
                plt.scatter(draps, dphis, dpts, marker='D')
                print(f"Added jet of {len(decendents)} tracks, {self.currently_avalible} pseudojets unfinished")
                plt.pause(0.05)
                input("Press enter for next pseudojet")
                self._remove_pseudojet(row)
        plt.show()


class SpectralMean(Spectral):
    """ """
    def _recalculate_one(self, remove_index, replace_index):
        """
        

        Parameters
        ----------
        remove_index :
            param replace_index:
        replace_index :
            

        Returns
        -------

        """
        # delete the larger index keep the smaller index
        assert remove_index > replace_index
        # delete the first row and column of the merge
        self._distances2 = np.delete(self._distances2, (remove_index), axis=0)
        self._distances2 = np.delete(self._distances2, (remove_index), axis=1)
        # and make its position in eigenspace
        new_position = (self._eigenspace[[remove_index]] + self._eigenspace[[replace_index]])*0.5
        # reshuffle the eigenspace to reflect the moevment in the floats and ints 
        if self.beam_particle:
        # move the replaced to the back, it will be repalced later
        # move the removed object to the back without replacement
        self._eigenspace = np.vstack((self._eigenspace[:remove_index],
                                      self._eigenspace[remove_index+1:],
                                      self._eigenspace[[remove_index]],
                                      self._eigenspace[[replace_index]]))
        self._eigenspace[replace_index] = new_position
        # get the new disntance in eigenspace
        if self.PTExponentPosition == 'eigenspace':
            exponent = 2 * self.PTExponentMultiplier
            pt_here = self._floats[replace_index][self._PT_col]**exponent
            pt_factor = np.fromiter((min(row[self._PT_col]**exponent, pt_here)
                                     for row in self._floats[:self.currently_avalible]),
                                    dtype=float) 
            new_distances2 = pt_factor*np.sum((self._eigenspace[:self.currently_avalible] - new_position)**2, axis=1)
        else:
            new_distances2 = np.sum((self._eigenspace[:self.currently_avalible] - new_position)**2, axis=1)
        if self.beam_particle:
            new_distances2[replace_index] = np.inf
        else:
            new_distances2[replace_index] = self.DeltaR**2
        self._distances2[replace_index] = new_distances2


class SpectralFull(Spectral):
    """ """
    def _recalculate_one(self, remove_index, replace_index):
        """
        

        Parameters
        ----------
        remove_index :
            param replace_index:
        replace_index :
            

        Returns
        -------

        """
        #print('reon_ful', end='\r', flush=True)
        self._calculate_distances()


cluster_classes = {"FastJet": Traditional, "HomeJet": Traditional,
                   "SpectralJet": Spectral, "SpectralMeanJet": SpectralMean,
                   "SpectralMAfterJet": SpectralMAfter, "SpectralFullJet": SpectralFull,
                   "SpectralAfterJet": SpectralAfter}


def get_jet_params(eventWise, jet_name, add_defaults=False):
    """
    

    Parameters
    ----------
    eventWise :
        param jet_name:
    add_defaults :
        Default value = False)
    jet_name :
        

    Returns
    -------

    """
    prefix = jet_name + "_"
    trim = len(prefix)
    columns = {name[trim:]: getattr(eventWise, name) for name in eventWise.hyperparameter_columns
               if name.startswith(prefix)}
    if add_defaults:
        if jet_name.startswith("SpectralMean"):
            defaults = SpectralMean.param_list
        elif jet_name.startswith("Spectral"):
            defaults = Spectral.param_list
        else:
            defaults = Traditional.param_list
        not_found = {name: defaults[name] for name in defaults
                     if name not in columns}
        columns = {**columns, **not_found}
    return columns


def filter_obs(eventWise, existing_idx_selection):
    """
    

    Parameters
    ----------
    eventWise :
        param existing_idx_selection:
    existing_idx_selection :
        

    Returns
    -------

    """
    assert eventWise.selected_index is not None
    has_track = eventWise.Particle_Track[existing_idx_selection.tolist()] >= 0
    has_tower = eventWise.Particle_Tower[existing_idx_selection.tolist()] >= 0
    observable = np.logical_or(has_track, has_tower)
    new_selection = existing_idx_selection[observable]
    return new_selection


def filter_ends(eventWise, existing_idx_selection):
    """
    

    Parameters
    ----------
    eventWise :
        param existing_idx_selection:
    existing_idx_selection :
        

    Returns
    -------

    """
    assert eventWise.selected_index is not None
    is_end = [len(c) == 0 for c in 
              eventWise.Children[existing_idx_selection.tolist()]]
    new_selection = existing_idx_selection[is_end]
    return new_selection


def filter_pt_eta(eventWise, existing_idx_selection, min_pt=.5, max_eta=2.5):
    """
    

    Parameters
    ----------
    eventWise :
        param existing_idx_selection:
    min_pt :
        Default value = .5)
    max_eta :
        Default value = 2.5)
    existing_idx_selection :
        

    Returns
    -------

    """
    assert eventWise.selected_index is not None
    # filter PT
    sufficient_pt = eventWise.PT[existing_idx_selection.tolist()] > min_pt
    updated_selection = existing_idx_selection[sufficient_pt]
    if "Pseudorapidity" in eventWise.columns:
        pseudorapidity_here = eventWise.Pseudorapidity[updated_selection.tolist()]
    else:
        theta_here = Components.ptpz_to_theta(eventWise.PT[updated_selection.tolist()], eventWise.Pz[updated_selection.tolist()])
        pseudorapidity_here = Components.theta_to_pseudorapidity(theta_here)
    pseudorapidity_choice = np.abs(pseudorapidity_here) < max_eta
    updated_selection = updated_selection[pseudorapidity_choice.tolist()]
    return updated_selection


def create_jetInputs(eventWise, filter_functions=[filter_obs, filter_pt_eta], batch_length=1000):
    """
    

    Parameters
    ----------
    eventWise :
        param filter_functions: (Default value = [filter_obs)
    filter_pt_eta :
        param batch_length: (Default value = 1000)
    filter_functions :
         (Default value = [filter_obs)
    filter_pt_eta] :
        
    batch_length :
         (Default value = 1000)

    Returns
    -------

    """
    # decide on run range
    eventWise.selected_index = None
    n_events = len(eventWise.Energy)
    start_point = len(getattr(eventWise, "JetInputs_Energy", []))
    if start_point >= n_events:
        print("Finished")
        return True
    end_point = min(n_events, start_point+batch_length)
    print(f" Will stop at {100*end_point/n_events}%")
    # sort out olumn names
    sources = ["PT", "Rapidity", "Phi", "Energy", "Px", "Py", "Pz"]
    for s in sources:
        if not hasattr(eventWise, s):
            print(f"EventWise lacks {s}")
            sources.remove(s)
    columns = ["JetInputs_" + c for c in sources]
    columns.append("JetInputs_SourceIdx")
    # the source column gives indices in the origin
    # construct the observable filter in advance
    contents = {"JetInputs_SourceIdx": list(getattr(eventWise, "JetInputs_SourceIdx", []))}
    for name in columns:
        contents[name] = list(getattr(eventWise, name, []))
    mask = []
    for event_n in range(start_point, end_point):
        if event_n % 100 == 0:
            print(f"{100*event_n/n_events}%", end='\r', flush=True)
        eventWise.selected_index = event_n
        idx_selection = np.arange(len(eventWise.PT))
        for filter_func in filter_functions:
            idx_selection = filter_func(eventWise, idx_selection)
        contents["JetInputs_SourceIdx"].append(idx_selection)
        mask_here = np.full_like(eventWise.PT, False, dtype=bool)
        mask_here[idx_selection] = True
        mask.append(awkward.fromiter(mask_here))
    mask = awkward.fromiter(mask)
    eventWise.selected_index = None
    try:
        for name, source_name in zip(columns, sources):
            contents[name] += list(getattr(eventWise, source_name)[start_point:end_point][mask])
        contents = {k:awkward.fromiter(v) for k, v in contents.items()}
        eventWise.append(**contents)
    except Exception as e:
        return contents, mask, columns, sources, e


def produce_summary(eventWise, to_file=True):
    """
    

    Parameters
    ----------
    eventWise :
        param to_file: (Default value = True)
    to_file :
         (Default value = True)

    Returns
    -------

    """
    assert eventWise.selected_index is not None
    n_inputs = len(eventWise.JetInputs_SourceIdx)
    summary = np.vstack((np.arange(n_inputs),
                         eventWise.JetInputs_Px,
                         eventWise.JetInputs_Py,
                         eventWise.JetInputs_Pz,
                         eventWise.JetInputs_Energy)).T
    summary = summary.astype(str)
    if to_file:
        header = f"# summary file for {eventWise}, event {eventWise.selected_index}\n"
        file_name = os.path.join(eventWise.dir_name, f"summary_observables.csv")
        with open(file_name, 'w') as summ_file:
            summ_file.write(header)
            writer = csv.writer(summ_file, delimiter=' ')
            writer.writerows(summary)
    else:
        rows = [' '.join(row) for row in summary]
        return '\n'.join(rows).encode()


def run_FastJet(eventWise, DeltaR, ExponentMultiplier, jet_name="FastJet", use_pipe=True):
    """
    

    Parameters
    ----------
    eventWise :
        param DeltaR:
    ExponentMultiplier :
        param jet_name: (Default value = "FastJet")
    use_pipe :
        Default value = True)
    DeltaR :
        
    jet_name :
         (Default value = "FastJet")

    Returns
    -------

    """
    assert eventWise.selected_index is not None
    if ExponentMultiplier == -1:
        # antikt algorithm
        algorithm_num = 1
    elif ExponentMultiplier == 0:
        algorithm_num = 2
    elif ExponentMultiplier == 1:
        algorithm_num = 0
    else:
        raise ValueError(f"ExponentMultiplier should be -1, 0 or 1, found {ExponentMultiplier}")
    program_name = "./tree_tagger/applyFastJet"
    if use_pipe:
        summary_lines = produce_summary(eventWise, False)
        out = run_applyfastjet(summary_lines, str(DeltaR).encode(), 
                                  str(algorithm_num).encode())
        fastjets = Traditional.read_fastjet(out, eventWise, jet_name=jet_name)
        return fastjets
    produce_summary(eventWise)
    subprocess.run([program_name, str(DeltaR), str(algorithm_num), eventWise.dir_name])
    fastjets = Traditional.read_fastjet(eventWise.dir_name, eventWise=eventWise, jet_name=jet_name)
    return fastjets


def run_applyfastjet(input_lines, DeltaR, algorithm_num, program_path="./tree_tagger/applyFastJet", tries=0):
    """
    Run applyfastjet, sending the provided input lines to stdin

    Parameters
    ----------
    input_lines : list of byte array
        contents of the input as byte arrays
    DeltaR :
        param algorithm_num:
    program_path :
        Default value = "./tree_tagger/applyFastJet")
    tries :
        Default value = 0)
    algorithm_num :
        

    Returns
    -------

    """
    # input liens should eb one long byte string
    assert isinstance(input_lines, bytes)
    process = subprocess.Popen([program_path, DeltaR, algorithm_num],
                               stdout=subprocess.PIPE,
                               stdin=subprocess.PIPE)
    while process.poll() is None:
        output_lines = None
        process_output = process.stdout.readline()
        if process_output[:2] == b' *': # all system prompts start with *
            # note that SusHi reads the input file several times
            if b'**send input file to stdin' in process_output:
                process.stdin.write(input_lines)
                process.stdin.flush()
                process.stdin.close()
            elif b'**output file starts here' in process_output:
                process.wait()  # ok let it complete
                output_lines = process.stdout.readlines()
    if output_lines is None:
        print("Error! No output, retrying that input")
        tries += 1
        if tries > 5:
            print("Tried this 5 times... already")
            st()
        # recursive call
        output_lines = run_applyfastjet(input_lines, DeltaR, algorithm_num, program_path, tries)
    return output_lines


def cluster_multiapply(eventWise, cluster_algorithm, cluster_parameters={}, jet_name=None, batch_length=100, silent=False):
    """
    

    Parameters
    ----------
    eventWise :
        param cluster_algorithm:
    cluster_parameters :
        Default value = {})
    jet_name :
        Default value = None)
    batch_length :
        Default value = 100)
    silent :
        Default value = False)
    cluster_algorithm :
        

    Returns
    -------

    """
    if jet_name is None and 'jet_name' in cluster_parameters:
        jet_name = cluster_parameters['jet_name']
    elif jet_name is None:
        for name, algorithm in cluster_classes.items():
            if algorithm == cluster_algorithm:
                jet_name = name
                break
    cluster_parameters["jet_name"] = jet_name  # enforce consistancy
    if cluster_algorithm == run_FastJet:
        # make sure fast jet uses the pipe
        cluster_parameters["use_pipe"] = True
        jet_class = Traditional
    else:
        # often the cluster algorithm is the jet class
        jet_class = cluster_algorithm
        # make sure the assignment is done on creation
        cluster_parameters["assign"] = True
    eventWise.selected_index = None
    dir_name = eventWise.dir_name
    n_events = len(eventWise.JetInputs_Energy)
    start_point = len(getattr(eventWise, jet_name+"_Energy", []))
    if start_point >= n_events:
        if not silent:
            print("Finished")
        return True
    end_point = min(n_events, start_point+batch_length)
    if not silent:
        print(f" Starting at {100*start_point/n_events}%")
        print(f" Will stop at {100*end_point/n_events}%")
    # updated_dict will be replaced in the first batch
    updated_dict = None
    checked = False
    has_eigenvalues = 'NumEigenvectors' in cluster_parameters
    if has_eigenvalues:
        eigenvalues = []
    for event_n in range(start_point, end_point):
        if event_n % 100 == 0 and not silent:
            print(f"{100*event_n/n_events}%", end='\r', flush=True)
        eventWise.selected_index = event_n
        if len(eventWise.JetInputs_PT) == 0:
            continue  # there are no observables
        jets = cluster_algorithm(eventWise, **cluster_parameters)
        if has_eigenvalues:
            eigenvalues.append(awkward.fromiter(jets.eigenvalues))
        jets = jets.split()
        if not checked and len(jets) > 0:
            assert jets[0].check_params(eventWise), f"Jet parameters don't match recorded parameters for {jet_name}"
            checked = True
        updated_dict = jet_class.create_updated_dict(jets, jet_name, event_n, eventWise, updated_dict)
    updated_dict = {name: awkward.fromiter(updated_dict[name]) for name in updated_dict}
    updated_dict[jet_name + "_Eigenvalues"] = awkward.fromiter(eigenvalues)
    eventWise.append(**updated_dict)
    return end_point == n_events


def plot_jet_spiders(ew, jet_name, event_num, colour=None, ax=None):
    """
    

    Parameters
    ----------
    ew :
        param jet_name:
    event_num :
        param colour: (Default value = None)
    ax :
        Default value = None)
    jet_name :
        
    colour :
         (Default value = None)

    Returns
    -------

    """
    if ax is None:
        ax = plt.gca()
    if colour is None:
        colour = tuple(np.random.rand(3))
    ew.selected_index = event_num
    child1 = getattr(ew, jet_name+"_Child1")
    energy = getattr(ew, jet_name+"_AveEnergy")
    rap= getattr(ew, jet_name+"_AveRapidity")
    phi = getattr(ew, jet_name+"_AvePhi")
    # mark the centers
    #ax.scatter(rap, phi, s=np.sqrt(energy), color=[colour], label=jet_name)
    # make lines to the inputs
    part_Energy = getattr(ew, jet_name+"_Energy")
    part_phi = getattr(ew, jet_name+"_Phi")
    part_rap = getattr(ew, jet_name+"_Rapidity")
    n_jets = len(energy)
    for jet_n in range(n_jets):
        if len(part_Energy) == 1:
            continue
        center_phi = phi[jet_n]
        center_rap = rap[jet_n]
        end_points = np.where([c==-1 for c in child1[jet_n]])[0]
        for end_idx in end_points:
            ax.plot([center_rap, part_rap[jet_n][end_idx]], [center_phi, part_phi[jet_n][end_idx]],
                    linewidth=np.sqrt(part_Energy[jet_n][end_idx]), alpha=0.5, color=colour)
        if jet_n == 0:
            plt.scatter(part_rap[jet_n][end_points], part_phi[jet_n][end_points], s=part_Energy[jet_n][end_points], c=[colour],label=jet_name)
        else:
            plt.scatter(part_rap[jet_n][end_points], part_phi[jet_n][end_points], s=part_Energy[jet_n][end_points], c=[colour])
    ax.set_xlabel("Rapidity")
    ax.set_ylabel("$\\phi$")
    ax.legend()
    ew.selected_index = None


def plot_spider(ax, colour, body, body_size, leg_ends, leg_size):
    """
    

    Parameters
    ----------
    ax :
        param colour:
    body :
        param body_size:
    leg_ends :
        param leg_size:
    colour :
        
    body_size :
        
    leg_size :
        

    Returns
    -------

    """
    alpha=0.4
    leg_size = np.sqrt(leg_size)
    for end, size in zip(leg_ends, leg_size):
        line = np.vstack((body, end))
        # work out if this leg crossed the edge
        if np.abs(line[0, 1] - line[1, 1]) > np.pi:
            # work out the x coord of the axis cross
            top = np.argmax(line[:, 1])
            bottom = (top+1)%2
            percent_to_top = np.abs((np.pi - line[top, 1])/(2*np.pi + line[bottom, 1] - line[top, 1]))
            x_top = line[top, 0] + (line[bottom, 0] - line[top, 0])*percent_to_top
            plt.plot([line[top, 0],  x_top], [line[top, 1], np.pi], 
                     c=colour, linewidth=size, alpha=alpha)
            plt.plot([line[bottom, 0],  x_top], [line[bottom, 1], -np.pi], 
                     c=colour, linewidth=size, alpha=alpha)
                     
        else:
            plt.plot(line[:, 0], line[:, 1],
                     c=colour, linewidth=size, alpha=alpha)
    plt.scatter([body[0]], [body[1]], c='black', marker='o', s=body_size-1)
    plt.scatter([body[0]], [body[1]], c=[colour], marker='o', s=body_size+1)


def flat_display(eventWise, event_n, home_jet_params, spectral_jet_params, spectral_class=SpectralFull):
    """
    

    Parameters
    ----------
    eventWise :
        param event_n:
    home_jet_params :
        param spectral_jet_params:
    spectral_class :
        Default value = SpectralFull)
    event_n :
        
    spectral_jet_params :
        

    Returns
    -------

    """
    ax = plt.gca()
    alpha=0.5
    # colourmap
    colours = plt.get_cmap('gist_rainbow')
    # create inputs if needed
    if "JetInputs_Energy" not in eventWise.columns:
        filter_funcs = [filter_ends, filter_pt_eta]
        if "JetInputs_Energy" not in eventWise.columns:
            create_jetInputs(eventWise, filter_funcs)
    # add tags if needed
    if "TagIndex" not in eventWise.columns:
        TrueTag.add_tag_particles(eventWise)
    # plot the location of the tag particles
    eventWise.selected_index = event_n
    tag_phis = eventWise.Phi[eventWise.TagIndex]
    tag_rapidity = eventWise.Rapidity[eventWise.TagIndex]
    plt.scatter(tag_rapidity, tag_phis, marker='d', c='g', label="Tags")
    pseudojet_traditional = Traditional(eventWise, **home_jet_params)
    pseudojet_traditional.assign_parents()
    pjets_traditional = pseudojet_traditional.split()
    # plot the pseudojets
    # traditional_colours = [colours(i) for i in np.linspace(0, 0.4, len(pjets_traditional))]
    traditional_colours = ['red' for _ in pjets_traditional]
    for c, pjet in zip(traditional_colours, pjets_traditional):
        obs_idx = [i for i, child1 in enumerate(pjet.Child1) if child1==-1]
        input_rap = np.array(pjet._floats)[obs_idx, pjet._Rapidity_col]
        input_phi = np.array(pjet._floats)[obs_idx, pjet._Phi_col]
        leg_ends = np.vstack((input_rap, input_phi)).T
        input_energy = np.array(pjet._floats)[obs_idx, pjet._Energy_col]
        plt.text(pjet.Rapidity, pjet.Phi-.1, str(pjet.PT)[:7], c=c)
        plot_spider(ax, c, [pjet.Rapidity, pjet.Phi], pjet.Energy, leg_ends, input_energy)
        #circle = plt.Circle((pjet.Rapidity, pjet.Phi), radius=DeltaR, edgecolor=c, fill=False)
        #ax.add_artist(circle)
    plt.plot([], [], c=c, alpha=alpha, label="HomeJets")
    pseudojet_spectral = SpectralMean(eventWise, **spectral_jet_params)
    pseudojet_spectral.assign_parents()
    pjets_spectral = pseudojet_spectral.split()
    # plot the pseudojets
    #spectral_colours = [colours(i) for i in np.linspace(0.6, 1.0, len(pjets_spectral))]
    spectral_colours = ['blue' for _ in pjets_spectral]
    for c, pjet in zip(spectral_colours, pjets_spectral):
        obs_idx = [i for i, child1 in enumerate(pjet.Child1) if child1==-1]
        input_rap = np.array(pjet._floats)[obs_idx, pjet._Rapidity_col]
        input_phi = np.array(pjet._floats)[obs_idx, pjet._Phi_col]
        leg_ends = np.vstack((input_rap, input_phi)).T
        input_energy = np.array(pjet._floats)[obs_idx, pjet._Energy_col]
        plot_spider(ax, c, [pjet.Rapidity, pjet.Phi], pjet.Energy, leg_ends, input_energy)
        plt.text(pjet.Rapidity, pjet.Phi+.1, str(pjet.PT)[:7], c=c)
        #circle = plt.Circle((pjet.Rapidity, pjet.Phi), radius=DeltaR, edgecolor=c, fill=False)
        #ax.add_artist(circle)
    plt.plot([], [], c=c, alpha=alpha, label="SpectralJet")
    plt.legend()
    plt.title("Jets")
    plt.xlabel("rapidity")
    plt.ylim(-np.pi, np.pi)
    plt.ylabel("phi")
    #plt.show()
    plt.savefig("test_plot.png")
    return pjets_spectral


if __name__ == '__main__':
    eventWise_path = InputTools.get_file_name("Where is the eventwise of collection fo eventWise? ", '.awkd')
    eventWise = Components.EventWise.from_file(eventWise_path)
    event_num = int(input("Event number "))
    home_jet_params = dict(DeltaR=1., ExponentMultiplier=-1, jet_name="HomeJetTest")
    spectral_jet_params = dict(DeltaR=0.15, ExponentMultiplier=0,
                               NumEigenvectors=4,
                               Laplacien='unnormalised',
                               AffinityType='exponent',
                               AffinityCutoff=('distance', 3),
                               jet_name="SpectralMeanTest")

    flat_display(eventWise, event_num, home_jet_params, spectral_jet_params)
