#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
import time


class RuntimeInfo:

    info_names = set( [
        'startepoch',
        'startdate',
        'finishepoch',
        'finishdate',
        'platform',
        'compiler',
        'cmdline',  # the vvtest command line
        'hostname',
        'rundir',  # the test results directory
        'curdir',
        'shortxdirs', # the --short-xdirs value, if any
        'python',  # the python executable path
        'vvtestdir',  # the (real) directory containing the vvtest script
        'PYTHONPATH',
        'PATH',
        'LOADEDMODULES',
    ] )

    def __init__(self, **kwargs):
        ""
        self.info = {}
        self._load_defaults()
        self.setInfo( **kwargs )

    def setInfo(self, **kwargs):
        ""
        for name,value in kwargs.items():

            assert name in RuntimeInfo.info_names

            self.info[ name ] = value

            if name == 'startepoch':
                self.info[ 'startdate' ] = time.ctime(value)
            elif name == 'finishepoch':
                self.info[ 'finishdate' ] = time.ctime(value)

    def getInfo(self, name, *default):
        ""
        if len( default ) > 0:
            return self.info.get( name, default[0] )
        return self.info[ name ]

    def asDict(self):
        ""
        return dict( self.info.items() )

    def _load_defaults(self):
        ""
        self.info['hostname']      = os.uname()[1]
        self.info['curdir']        = os.getcwd()
        self.info['python']        = sys.executable
        self.info['PYTHONPATH']    = os.environ.get( 'PYTHONPATH', '' )
        self.info['PATH']          = os.environ.get( 'PATH', '' )
        self.info['LOADEDMODULES'] = os.environ.get( 'LOADEDMODULES', '' )
