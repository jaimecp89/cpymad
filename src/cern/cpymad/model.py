#-------------------------------------------------------------------------------
# This file is part of PyMad.
#
# Copyright (c) 2011, CERN. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# 	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#-------------------------------------------------------------------------------
'''
.. module: cpymad.model

Cython implementation of the model api.

.. moduleauthor:: Yngve Inntjore Levinsen <Yngve.Inntjore.Levinsen@cern.ch>

'''

from __future__ import absolute_import

import logging
import os
import sys
import yaml

from .model_locator import ModelData
from .madx import Madx


class Model(object):
    '''
    Model class implementation. the model spawns a madx instance in a separate process.
    this has the advantage that you can run separate models which do not affect each other.

    To load a Model object using the default ModelLocator use the static
    constructor method ``Model.from_name``. The default constructor should
    be invoked with a ModelData instance.

    '''
    @classmethod
    def from_name(cls, model, *args, **kwargs):
        """
        Create a Model object from its name.

        :param string model: Name of the model
        :param tuple args: Positional parameters as needed by ``__init__``
        :param dict kwargs: Keyword parameters as needed by ``__init__``

        This constructor is provided for backward compatibility. To specify
        where your model data is loaded from you should create and use your
        own custom cern.cpymad.model_locator.ModelLocator.

        """
        from .service import default_model_locator
        mdata = default_model_locator.get_model(model)
        return cls(mdata, *args, **kwargs)


    def __init__(self, model,
                 sequence='',optics='',
                 histfile='',
                 madx=None,
                 logger=None):
        """
        Construct a Model object.

        :param ModelData model: model data as acquired through a ModelLocator
        :param string sequence: Name of the default sequence to use
        :param string optics: Name of optics to load, string or list of strings.
        :param string histfile: Name of file which will contain all Mad-X commands called.

        For backward compatibility reasons, the first parameter can also be
        the name of the model to be loaded. This is equivalent to the
        preferred Model.from_name() constructor.

        """
        self._madx = madx or Madx(histfile)
        self._madx.verbose(False)
        self._log = logger or logging.getLogger(__name__)

        if isinstance(model, ModelData):
            mdata = model
        else:
            from .service import default_model_locator
            mdata = default_model_locator.get_model(model)

        self.mdata = mdata
        self._mdef = mdata.model

        self._active={'optic':'','sequence':'','range':''}

        self._setup_initial(sequence,optics)

    # API stuff:
    @property
    def name(self):
        return self.mdata.name

    @property
    def mdef(self):
        return self._mdef.copy()


    def set_sequence(self,sequence='',madrange=''):
        '''
        Set a new active sequence...
        '''
        if not sequence:
            if not self._active['sequence']:
                self._active['sequence']=self._mdef['default-sequence']
            sequence=self._active['sequence']
        if sequence in self._mdef['sequences']:
            self._active['sequence']=sequence
            if madrange:
                self.set_range(madrange)
            else:
                self.set_range(self._mdef['sequences'][sequence]['default-range'])
        else:
            raise KeyError("You tried to activate a non-existing sequence")

    def set_range(self,madrange=''):
        '''
        Sets the active range to madrange. Must be defined in the
        currently active sequence...
        If madrange is empty, sets the range to default-range unless
        another range is already set.
        '''
        seqdict=self._mdef['sequences'][self._active['sequence']]
        if madrange:
            if madrange not in seqdict['ranges']:
                raise KeyError("%s is not a valid range name, available ranges: '%s'" % (madrange,"' '".join(seq['ranges'].keys())))
            self._active['range']=madrange
        else:
            if not self._active['range']:
                self._active['range']=seqdict['default-range']

    def _setup_initial(self,sequence,optics):
        '''
        Initial setup of the model
        '''
        for ifile in self._mdef['init-files']:
            self._call(ifile)

        # initialize all sequences..
        for seq in self._mdef['sequences']:
            self._init_sequence(seq)
        # then we set the default one..
        self.set_sequence(sequence)
        if isinstance(optics, str):
            self.set_optic(optics)
        elif isinstance(optics, list):
            for o in optics:
                self.set_optic(o)
        # To keep track of whether or not certain things are already called..
        self._apercalled={}
        self._twisscalled={}
        for seq in self.get_sequences():
            self._apercalled[seq.name]=False
            self._twisscalled[seq.name]=False

    def _init_sequence(self,sequence):
        '''
        Initialize sequence
        '''
        bname=self._mdef['sequences'][sequence]['beam']
        bdict=self.get_beam(bname)
        self.set_beam(bdict)

    def get_beam(self,bname):
        '''
         Returns the beam definition in form
         of a dictionary.

         You can then change parameters in this dictionary
         as you see fit, and use set_beam() to activate that
         beam.
        '''
        return self._mdef['beams'][bname]

    def set_beam(self,beam_dict):
        '''
         Set the beam from a beam definition
         (dictionary)
        '''
        self._madx.command.beam(**beam_dict)

    def _cmd(self, cmd):
        return self._madx.command(cmd)

    def __str__(self):
        return self.name

    def _call(self,fdict):
        with self.mdata.get_by_dict(fdict).filename() as fpath:
            self.call(fpath)

    def call(self,filepath):
        '''
         Call a file in Mad-X. Give either
         full file path or relative.
        '''
        if not os.path.isfile(filepath):
            raise ValueError("You tried to call a file that doesn't exist: "+filepath)

        self._log.debug("Calling file: %s", filepath)
        return self._madx.call(filepath)

    def evaluate(self, expr):
        """
        Evaluate a string expression and return the resulting float.

        :param string expr:

        """
        return self._madx.evaluate(expr)

    def has_sequence(self,sequence):
        '''
         Check if model has the sequence.

         :param string sequence: Sequence name to be checked.
        '''
        return sequence in self.get_sequence_names()

    def has_optics(self,optics):
        '''
         Check if model has the optics.

         :param string optics: Optics name to be checked.
        '''
        return optics in self._mdef['optics']

    def set_optic(self,optic):
        '''
         Set new optics.

         :param string optics: Optics name.

         :raises KeyError: In case you try to set an optics not available in model.
        '''

        if optic=='':
            optic=self._mdef['default-optic']
        if self._active['optic'] == optic:
            self._log.info("Optics already initialized: %s", optic)
            return 0

        # optics dictionary..
        odict=self._mdef['optics'][optic]

        for strfile in odict['init-files']:
            self._call(strfile)

        # knobs dictionary.. we don't have that yet..
        #for f in odict['knobs']:
            #if odict['knobs'][f]:
                #self.set_knob(f,1.0)
            #else:
                #self.set_knob(f,0.0)

        self._active['optic']=optic

    def set_knob(self,knob,value):
        kdict = self._mdef['knobs']
        for e in kdict[knob]:
            val = kdict[knob][e] * value
            self._madx.command(**{e: val})

    def get_sequences(self):
        '''
         Returns a list of loaded sequences.
        '''
        return self._madx.get_sequences()

    def get_sequence_names(self):
        """
        Return list of all loaded sequences.
        """
        return self._madx.get_sequence_names()

    def list_optics(self):
        '''
         Returns an iterable of available optics
        '''
        return self._mdef['optics'].keys()

    def list_ranges(self,sequence=None):
        '''
         Returns a list of available ranges for the sequence.
         If sequence is not given, returns a dictionary structured as
         {sequence1:[range1,range2,...],sequence2:...}

         :param string sequence: sequence name.
        '''
        if sequence is None:
            ret={}
            for s in self.get_sequences():
                ret[s.name]=list(self._mdef['sequences'][s]['ranges'].keys())
            return ret

        return list(self._mdef['sequences'][sequence]['ranges'].keys())

    def list_beams(self):
        '''
         Returns an iterable of available beams
        '''
        return self._mdef['beams'].keys()

    def _get_twiss_initial(self,sequence='',madrange='',name=''):
        '''
        Returns the dictionary for the twiss initial conditions.
        If name is not defined, using default-twiss
        '''
        rangedict=self._get_range_dict(sequence=sequence,madrange=madrange)
        madrange=self._active['range']
        if name:
            if name not in rangedict['twiss-initial-conditions']:
                raise ValueError('twiss initial conditions with name '+name+' not found in range '+madrange)
            return rangedict['twiss-initial-conditions'][name]
        else:
            return rangedict['twiss-initial-conditions'][rangedict['default-twiss']]


    def twiss(self,
              sequence='',
              columns=['name','s','betx','bety','x','y','dx','dy','px','py','mux','muy','l','k1l','angle','k2l'],
              pattern=['full'],
              madrange='',
              fname='',
              use=True
              ):
        '''
         Run a TWISS on the model.

         Warning for ranges: Currently TWISS with initial conditions is NOT
         implemented!

         :param string sequence: Sequence, if empty, using active sequence.
         :param string columns: Columns in the twiss table, can also be list of strings
         :param string madrange: Optional, give name of a range defined for the model.
         :param string fname: Optionally, give name of file for tfs table.
         :param bool use: Call use before twiss.
        '''
        # set sequence/range...
        if madrange:
            self.set_sequence(sequence,madrange)
        else:
            self.set_sequence(sequence)
        sequence=self._active['sequence']
        _madrange=self._active['range']

        if self._apercalled.get(sequence):
            raise ValueError("BUG in Mad-X: Cannot call twiss after aperture..")

        seqdict=self._mdef['sequences'][sequence]
        rangedict=seqdict['ranges'][_madrange]

        if 'twiss-initial-conditions' in rangedict:
            # this looks like a bug check to me (0 evaluates to False):
            twiss_init = dict(
                (key, val)
                for key, val in self._get_twiss_initial(sequence,_madrange).items()
                if val)
        else:
            twiss_init = None

        res = self._madx.twiss(
            sequence=sequence,
            pattern=pattern,
            columns=columns,
            madrange=[rangedict["madx-range"]["first"],rangedict["madx-range"]["last"]],
            fname=fname,
            twiss_init=twiss_init,
            use=use)
        # we say that when the "full" range has been selected,
        # we can set this to true. Needed for e.g. aperture calls
        if not madrange:
            self._twisscalled[sequence]=True
        return res

    def survey(self,
               sequence='',
               columns='name,l,s,angle,x,y,z,theta',
               madrange='',
               fname='',
               use=True):
        '''
         Run a survey on the model.

         :param string sequence: Sequence, if empty, using active sequence.
         :param string columns: Columns in the twiss table, can also be list of strings
         :param string fname: Optionally, give name of file for tfs table.
         :param bool use: Call use before survey.
        '''
        self.set_sequence(sequence)
        sequence=self._active['sequence']

        this_range=''
        if madrange:
            rangedict=self._get_range_dict(sequence=sequence,madrange=madrange)
            this_range=rangedict['madx-range']

        return self._madx.survey(
            sequence=sequence,
            columns=columns,
            madrange=this_range,
            fname=fname,
            use=use)

    def aperture(self,
               sequence='',
               madrange='',
               columns='name,l,s,n1,aper_1,aper_2,aper_3,aper_4',
               fname='',
               use=False):
        '''
         Get the aperture from the model.

         :param string sequence: Sequence, if empty, using active sequence.
         :param string madrange: Range, if empty, the full sequence is chosen.
         :param string columns: Columns in the twiss table, can also be list of strings
         :param string fname: Optionally, give name of file for tfs table.
         :param bool use: Call use before aperture.
        '''
        self.set_sequence(sequence)
        sequence=self._active['sequence']

        if not self._twisscalled.get(sequence):
            self.twiss(sequence)
        # Calling "basic aperture files"
        if not self._apercalled[sequence]:
            for afile in self._mdef['sequences'][sequence]['aperfiles']:
                self._call(afile)
            self._apercalled[sequence]=True
        # getting offset file if any:
        # if no range was selected, we ignore offsets...
        offsets=None
        this_range=''
        if madrange:
            rangedict=self._get_range_dict(sequence=sequence,madrange=madrange)
            this_range=rangedict['madx-range']
            if 'aper-offset' in rangedict:
                offsets = self.mdata.get_by_dict(rangedict['aper-offset']).filename()

        args={'sequence': sequence,
              'madrange': this_range,
              'columns': columns,
              'fname': fname,
              'use': use}

        if offsets:
            with offsets as offsets_filename:
                return self._madx.aperture(offsets=offsets_filename, **args)
        else:
            return self._madx.aperture(**args)


    def match(
            self,
            constraints,
            vary,
            weight=None,
            method=['lmdif'],
            sequence = '',
            fname=''):
        """
        Perform a matching operation.

        See :func:`cern.madx.match` for a description of the parameters.
        """
        # set sequence/range...
        self.set_sequence(sequence)
        sequence=self._active['sequence']
        _madrange=self._active['range']

        seqdict=self._mdef['sequences'][sequence]
        rangedict=seqdict['ranges'][_madrange]

        def is_match_param(v):
            return v.lower() in ['rmatrix', 'chrom', 'beta0', 'deltap',
                    'betx','alfx','mux','x','px','dx','dpx',
                    'bety','alfy','muy','y','py','dy','dpy' ]

        if 'twiss-initial-conditions' in rangedict:
            twiss_init = dict(
                (key, val)
                for key, val in self._get_twiss_initial(sequence,_madrange).items()
                if is_match_param(key))
        else:
            twiss_init = None

        self._madx.match(
            sequence=sequence,
            constraints=constraints,
            vary=vary,
            weight=weight,
            method=method,
            fname=fname,
            twiss_init=twiss_init)
        return self.twiss(sequence=sequence)

    def _get_ranges(self,sequence):
        return self._mdef['sequences'][sequence]['ranges'].keys()

    def _get_range_dict(self,sequence='',madrange=''):
        '''
        Returns the range dictionary. If sequence/range isn't given,
        returns default for the model
        '''
        if sequence=='':
            sequence=self._active['sequence']
        elif sequence not in self._mdef['sequences']:
            raise ValueError("%s is not a valid sequence name, available sequences: '%s'" % (sequence,"' '".join(self._mdef['sequences'].keys())))

        seqdict=self._mdef['sequences'][sequence]
        if madrange:
            self.set_range(madrange)
        return seqdict['ranges'][self._active['range']]



def save_model(model_def,filename):
    '''
    Saves the model definition defined by the dictionary model_def
    to file filename. The file is in YAML format (or JSON). We do not check
    that the model is valid in any way.

    It is recommended that you rather use the modeldefs.model.save_model,
    once it is ready.
    '''
    yaml.safe_dump(model_def,stream=open(filename,'w'))

