''' module for data reading tools '''
import os
import sys
import time
import datetime
import csv
from ast import literal_eval
from pathlib import Path
from copy import deepcopy
from ipdb import set_trace as st
import torch
import numpy as np
from tree_tagger import Constants, Datasets, LinkingNN
from matplotlib import pyplot as plt
import matplotlib.animation


def remove_file_extention(path):
    suffix = Path(path).suffix
    if len(suffix) == 0:
        return path
    return path[:-len(suffix)]


def str_is_type(s_type, s, accept_none=False):
    if s is None and accept_none:
        return True
    if isinstance(s, s_type) or s is None: # the conversion already happened
        return True
    try:
        s_type(s)
        return True
    except ValueError:
        return False


class Run:
    # the list arguments in the info line
    # given inorder of precidence when performing comparison
    setting_names = ["net_type", "data_folder",  # nature of the net itself
                     "weight_decay", # minor net parameters
                     "batch_size", "loss_type", "inital_lr",  # training parameters
                     "auc", "lowest_loss", "notes"] # results
    loss_functions = ["BCE"]
    # the tests for identifying the arguments
    arg_tests = {"net_type"    : lambda s: True,
                 "data_folder" : os.path.exists,
                 "batch_size"  : lambda s: str_is_type(int, s),
                 "inital_lr"   : lambda s: str_is_type(float, s),
                 "weight_decay": lambda s: str_is_type(float, s),
                 "loss_type"   : lambda s: s.upper() in Run.loss_functions,
                 "auc"         : lambda s: str_is_type(float, s) or (s is None),
                 "lowest_loss" : lambda s: str_is_type(float, s) or (s is None),
                 "notes"       : lambda s: True}

    arg_convert = {"net_type"    : lambda s: s,
                   "data_folder" : lambda s: s,
                   "batch_size"  : lambda s: int(s),
                   "inital_lr"   : lambda s: float(s),
                   "weight_decay": lambda s: float(s),
                   "loss_type"   : lambda s: s.upper(),
                   "auc"         : lambda s: None if s is None else float(s),
                   "lowest_loss" : lambda s: None if s is None else float(s),
                   "notes"       : lambda s: s}

    arg_defaults = {"net_type"    : "default",
                    "data_folder" : "tst",
                    "time"        : 3000,
                    "batch_size"  : 1000,
                    "inital_lr"   : 0.1,
                    "weight_decay": 0.01,
                    "loss_type"   : loss_functions[0],
                    "auc"         : None,
                    "lowest_loss" : None,
                    "notes"       : ""}
                          
    def __init__(self, folder_name, run_name, accept_empty=False, writing=False):
        self.writing = writing  
        self.written = False  # flip to true after first write
        # because this method is called frequently, pull the if logic outside
        if writing: # a writing run is inefficient, but will continuously generate output
            def append(line):
                # the line to append must have a value for every column
                assert len(line) == len(self.column_headings), "tried to append values not equal to number of columns"
                self.table = np.vstack((self.table, line))
                if self.written:  # then jsut update
                    with open(self.progress_file_name, 'a') as pf:
                        writer = csv.writer(pf, delimiter=' ')
                        writer.writerow(line)
                else:  # then create the write
                    self.write(with_nets=False)
        else:  # this is the fast version, even skip the assert
            def append(line):
                self.table = np.vstack((self.table, line))
        self.append = append
        # locate the write file
        self.folder_name = folder_name
        self.base_name = os.path.join(folder_name, run_name)
        self.progress_file_name = self.base_name + ".txt"
        with open(self.progress_file_name, 'r') as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=' ')
            # the first line in the file is info
            info_line = next(csv_reader)
            # the line under this is the columns
            try:
                self.column_headings = next(csv_reader)
                # if it exists the run is not empty
                self.empty_run = False
            except StopIteration:
                if accept_empty:
                    self.empty_run = True
                    self.table = np.empty(0)  # generate an empty table for now
                else:
                    # not a full run
                    raise ValueError
            if not self.empty_run:
                # the first column is always time_stamps
                if self.column_headings[0] != 'time_stamps':
                    raise ValueError
                # then tehre is the table
                table = []
                for row in csv_reader:
                    table.append(row)
                self.table = np.array(table, dtype=np.float)
                # if the table is smaller than the column headings drop those columns
                if self.table.shape[1] < len(self.column_headings):
                    self.column_headings = self.column_headings[:self.table.shape[1]]
                assert len(self.column_headings) == self.table.shape[1], "Number columns not equal to number column headdings"
        # now process the info line
        self.settings = self.process_info_line(info_line)
        self.dataset = self._load_dataset()
        # if the net is empty these things should not exist
        if self.empty_run:
            if self.settings['auc'] is not None:
                print("Warning, found auc {} in empty run".format(self.settings['auc']))
                self.settings['auc'] = None
            if self.settings['lowest_loss'] is not None:
                print("Warning, found lowest_loss {} in empty run".format(self.settings['lowest_loss']))
                self.settings['lowest_loss'] = None
        self.settings["pretty_name"] = run_name
        # also make file names for the best and last nets
        net_extention = ".torch"
        self.last_net_files = [self.base_name + "_last_" + self.settings['net_type'] + net_extention]
        self.best_net_files = [self.base_name + "_best_" + self.settings['net_type'] + net_extention]
        # check to see if either of these exist and load if so
        self.__best_net_state_dicts = None  # create the attribute
        self.__last_net_state_dicts = None
        try:
            last_net_state_dicts = [torch.load(name, map_location='cpu')
                                    for name in self.last_net_files]
            self.last_nets = self._nets_from_state_dict(last_net_state_dicts)
        except FileNotFoundError:
            # if the run is not empty there should be a last net
            if not self.empty_run:
                print("Warning; not an empty run, but no last net found!")
        try:
            best_net_state_dicts = [torch.load(name, map_location='cpu')
                                    for name in self.best_net_files]
            self.set_best_state_dicts(best_net_state_dicts, self.settings['lowest_loss'])
        except FileNotFoundError:
            if not self.empty_run:
                print("Warning; not an empty run, but no best net found!")
    
    def _load_dataset(self):
        raise NotImplementedError

    def _nets_from_state_dict(self):
        raise NotImplementedError

    def __process_idx(self, idx):
        # if there is only one item make the second item a total slice
        if not isinstance(idx, tuple):
            idx = (idx, slice(None))
        elif len(idx) == 1:
            idx = (idx[0], slice(None))
        else:
            assert len(idx) < 3, "Only two dimensions to the run record!"
        processed_idx = [None, None]
        for n in range(2):
            i = idx[n]
            # put numpy arrays to lists
            if isinstance(i, np.ndarray):
                i = list(i)
            # deal with the column headidings case
            if n == 1:
                if isinstance(i, str):
                    assert i in self.column_headings, "index {} not in column_headings"
                    i = self.column_headings.index(i)
                elif isinstance(i, list) and set(i).issubset(self.column_headings):
                    # if it is a list of coumn headings convert them
                    i = [self.column_headings.index(ie) for ie in i]
            # now the whole thing should be ints or a slice
            if isinstance(i, list):
                i = [int(ie) for ie in i]
            elif not isinstance(i, slice): # dont need to convert slices
                i = int(i)
            processed_idx[n] = i
        return tuple(processed_idx)

    def __getitem__(self, idx):
        processed_idx = self.__process_idx(idx)
        return self.table[processed_idx]

    def __setitem__(self, idx, value):
        processed_idx = self.__process_idx(idx)
        self.table[idx] = value


    def __len__(self):
        return self.table.shape[0]

    def __str__(self):
        return "{}; net {}, batch {}"\
                .format(self.base_name,
                        self.settings["net_type"],
                        self.settings["batch_size"])

    # inequlity comparisons
    def __eq__(self, other):
        tables_eq = np.allclose(self.table, other.table)
        names_eq = self.setting_names == other.setting_names
        settings_eq = np.all([self.settings[name] == other.settings[name]
                        for name in self.setting_names])
        return tables_eq and names_eq and settings_eq


    def __ne__(self, other):
        return not self == other


    def __gt__(self, other):
        for name in self.setting_names:
            seset = self.settings[name]
            otset = other.settings[name]
            if seset is not None and otset is not None:
                if seset != otset:
                    return seset > otset
        # if we get here they are all either none or equal
        return False

    def __lt__(self, other):
        for name in self.setting_names:
            seset = self.settings[name]
            otset = other.settings[name]
            if seset is not None and otset is not None:
                if seset != otset:
                    return seset < otset
        # if we get here they are all either none or equal
        return False

    def __le__(self, other):
        return not self > other
    
    def __ge__(self, other):
        return not self < other

    @property
    def column_headings(self):
        return self.__column_headings

    @column_headings.setter
    def column_headings(self, column_headings):
        # we can only set column headdings if there arnt ay already
        assert not hasattr(self, 'column_headings'), "Column headdings already set!"
        # there should definetly be column headdings before data in the table
        assert not hasattr(self, 'table') or len(self.table)==0, "Data in table before column headdings chosen!"
        self.__column_headings = column_headings
        self.table = np.array([]).reshape((0, len(self.column_headings)))


    def process_info_line(self, info_line):
        # kill empty strings
        info_line = list(filter(None, info_line))
        # if the info line looks like a dict
        # then we can just read it
        info_line = ''.join(info_line)
        args = literal_eval(info_line)
        assert isinstance(args, dict)
        # and convert he values
        for key in (set(args.keys() & set(Run.arg_tests.keys()))):
            # check the input is valid
            assert Run.arg_tests[key](args[key]), "problem with {}".format(key)
            # convert and store
            args[key] = Run.arg_convert[key](args[key])
        # find out if anything didn't get added
        for arg_name in self.setting_names:
            if arg_name not in args.keys():
                print("Missing {}, assuming default value {}"
                      .format(arg_name, self.arg_defaults[arg_name]))
                args[arg_name] = self.arg_defaults[arg_name]
        return args

    def get_time(self):
        # pick the first timestamp
        t_0 = self['time_stamps', 0]
        time_0 = time.gmtime(t_0)
        self.time = datetime.datetime(*time_0[:6])
        return self.time

    def add_auc(self):
        _, _, auc = calculate_roc(self, self.settings['data_folder'])
        self.settings['auc'] = auc

    def write(self, with_nets=True):
        # just clear the file and start from scratch
        with open(self.progress_file_name, 'w') as pf:
            writer = csv.writer(pf, delimiter=' ')
            writer.writerow([str(self.settings)])
            writer.writerow(self.column_headings)
            for row in self.table:
                writer.writerow(row)
        if with_nets:
            # save the best and last nets, they should exist by now
            for net, file_name in zip(self.__best_net_state_dicts, self.best_net_files):
                torch.save(net, file_name)
            try:
                for net, file_name in zip(self.__last_net_state_dicts, self.last_net_files):
                    torch.save(net, file_name)
            except AttributeError:
                print("Didn't find a last_net")
        self.written = True

    @property
    def best_nets(self):
        return self._nets_from_state_dict(self.__best_net_state_dicts)

    @best_nets.setter
    def best_nets(self, param_dicts):
        # don't allow direct setting of the best net
        # must use set method to ensure we also get the lowest loss
        raise AttributeError("Do not set this directly, use set_best_net")

    def set_best_state_dicts(self, param_dicts, lowest_loss):
        # could make an assertion about this loss being lower thant previous ones,
        # but as I expect this code to be called many times I will omit it
        self.settings['lowest_loss'] = float(lowest_loss)
        self.__best_net_state_dicts = deepcopy(param_dicts)

    @property
    def last_nets(self):
        return self._nets_from_state_dict(self.__last_net_state_dicts)

    @last_nets.setter
    def last_nets(self, param_dicts):
        # if we were given a net make it a state dict
        if not isinstance(param_dicts[0], dict):
            param_dicts = [p.state_dict() for p in param_dicts]
        self.__last_net_state_dicts = deepcopy(param_dicts)


class LinkingRun(Run):
    # the list arguments in the info line
    # given inorder of precidence when performing comparison
    setting_names = Run.setting_names + ["latent_dimension",
                                 "database_name", "hepmc_name"]
    # the tests for identifying the arguments
    arg_tests = {**Run.arg_tests,
                 "database_name" : os.path.exists,
                 "hepmc_name"  : os.path.exists,
                 "latent_dimension" : lambda s: str_is_type(int, s)}

    arg_convert = {**Run.arg_convert, 
                   "database_name" : lambda s: s,
                   "hepmc_name"  : lambda s: s,
                   "latent_dimension" : lambda s: int(s)}

    arg_defaults = {"data_folder"   : "big_ds",
                    "database_name" : "/home/henry/lazy/h1bBatch2.db",
                    "hepmc_name"  : "/home/henry/lazy/h1bBatch2.hepmc",
                    "time"        : 3000,
                    "batch_size"  : 10,
                    "inital_lr"   : 0.01,
                    "weight_decay": 0.01,
                    "net_type"    : "Linker",
                    "latent_dimension" : 10,
                    "auc"         : None,
                    "lowest_loss" : None,
                    "notes"       : ""}
    net_list = ["tower_net", "track_net"]
                          
    def __init__(self, folder_name, run_name, accept_empty=False, writing=False):
        super().__init__(folder_name, run_name, accept_empty, writing)
        self.last_net_files = []
        self.best_net_files = []
        net_extention = ".torch"
        for name in self.net_list:
            self.last_net_files.append(self.base_name + "_last_" + name + net_extention)
            self.best_net_files.append(self.base_name + "_best_" + name + net_extention)
    
    def _load_dataset(self, shuffle=False):
        dataset = Datasets.TracksTowersDataset(folder_name=self.settings['data_folder'],
                                               database_name=self.settings['database_name'],
                                               hepmc_name=self.settings['hepmc_name'],
                                               shuffle=shuffle)
        return dataset
        

    def _nets_from_state_dict(self, state_dicts):
        towers_projector = LinkingNN.Latent_projector(self.dataset.tower_dimensions,
                                                      self.settings['latent_dimension'])
        towers_projector.load_state_dict(state_dicts[0])
        tracks_projector = LinkingNN.Latent_projector(self.dataset.track_dimensions,
                                                      self.settings['latent_dimension'])
        tracks_projector.load_state_dict(state_dicts[1])
        return [towers_projector, tracks_projector]


class RecursiveRun(Run):
    arg_defaults = {"data_folder" : "fakereco",
                    "time"        : 3000,
                    "batch_size"  : 10,
                    "inital_lr"   : 0.01,
                    "weight_decay": 0.01,
                    "net_type"    : "Recursive",
                    "auc"         : None,
                    "lowest_loss" : None,
                    "notes"       : ""}
                          
    def __init__(self, folder_name, run_name, accept_empty=False, writing=False):
        super().__init__(folder_name, run_name, accept_empty, writing)
    
    def _load_dataset(self, shuffle=False):
        dataset = Datasets.JetTreesDataset(dir_name=self.settings['data_folder'])
        return dataset
        

    def _nets_from_state_dict(self, state_dicts):
        towers_projector = LinkingNN.Latent_projector(self.dataset.tower_dimensions,
                                                      self.settings['latent_dimension'])
        towers_projector.load_state_dict(state_dicts[0])
        tracks_projector = LinkingNN.Latent_projector(self.dataset.track_dimensions,
                                                      self.settings['latent_dimension'])
        tracks_projector.load_state_dict(state_dicts[1])
        return [towers_projector, tracks_projector]


def calculate_roc(run, focus=0, target_flavour='b', ddict_name=None):
    raise NotImplementedError

def get_LinkingProjections(nets, dataset, event_num):
    data_event = dataset[event_num]
    towers_data, tracks_data, proximities, MC_truth = event_data
    tower_net, track_net = nets
    towers_projection = tower_net(towers_data)
    tracks_projection = track_net(tracks_data)
    return towers_projection, tracks_projection

plt.ion()

def distances(track_num, tracks_projections, towers_projects):
    this_track = tracks_projections[track_num]
    track_dist = np.sqrt(np.sum(np.square(tracks_projections - this_track),
                                axis=1))
    tower_dist = np.sqrt(np.sum(np.square(towers_projections - this_track),
                                axis=1))
    return track_dist, tower_dist


class Liveplot:
    def __init__(self, run):
        self.run = run
        data = []
        end_time = self.run.settings['time'] + time.time() + 10
        self.xmin, self.xmax = time.time(), end_time
        self.on_launch()
        while time.time() < end_time and os.path.exists("continue"):
            time.sleep(0.1)
            line_data = self._try_line()
            if line_data:
                data.append(line_data)
                self._update(data)

    def on_launch(self):
        # wait for the run to be assigned column headdings
        while not self.run.written:
            time.sleep(0.5)
        # set up plots
        self.figure, self.ax_array = plt.subplots(4, 1, sharex=True)
        self.time_stamps_idx = self.run.column_headings.index("time_stamps")
        plot_cols = ["training_loss", "validation_loss", "test_loss", "mag_weights"]
        self.plot_idx = [self.run.column_headings.index(name) for name in plot_cols]
        self.lines = []
        for i, ax in enumerate(self.ax_array):
            ax.set_ylabel(plot_cols[i])
            self.lines.append(ax.plot([], [])[0])
            #Autoscale on unknown axis and known lims on the other
            ax.set_autoscaley_on(True)
            ax.set_xlim(self.xmin, self.xmax)
        self.ax_array[-1].set_xlabel("time_steps")
        file_name = self.run.progress_file_name
        # open the file
        self.inp_file = open(file_name)
        # first line is settings
        self.inp_file.readline()
        # second line is column headdings
        self.inp_file.readline()

    def _update(self, data):
        # update the plot
        time_stamps = [d[self.time_stamps_idx] for d in data]
        for line, idx in zip(self.lines, self.plot_idx):
            values = [d[idx] for d in data]
            line.set_data(time_stamps, values)
        plt.draw()
        for ax in self.ax_array:
            #Need both of these in order to rescale
            ax.relim()
            ax.autoscale_view()
        #We need to draw *and* flush
        self.figure.canvas.draw()
        self.figure.canvas.flush_events()

    def _try_line(self):
        line = self.inp_file.readline()
        if line:
            data = [float(x) for x in line.split(' ')]
            return data

if __name__ == '__main__':
    pass
    
