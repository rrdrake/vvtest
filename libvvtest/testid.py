#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import dirname, normpath
from os.path import join as pjoin

import hashlib


class TestID:

    def __init__(self, testname, filepath, params, staged_names):
        ""
        self.name = testname
        self.filepath = filepath
        self.params = params
        self.staged = staged_names

        self.short = 100

    def setShorten(self, value):
        ""
        self.short = value

    def getStageNames(self):
        ""
        return self.staged

    def computeExecuteDirectory(self, shorten=True):
        ""
        bname = self.name

        paramL = self._get_parameters_as_list( compress_stage=True)
        if len( paramL ) > 0:
            bname += '.' + '.'.join(paramL)

        if shorten:
            bname = self._compute_shortened_name( bname )

        dname = dirname( self.filepath )

        return normpath( pjoin( dname, bname ) )

    def computeDisplayString(self):
        ""
        displ = self.computeExecuteDirectory( shorten=False )

        if self.staged:

            stage_name = self.staged[0]
            param_names = self.staged[1:]

            paramL = list( param_names )
            paramL.sort()
            pL = []
            for param in paramL:
                pL.append( param+'='+self.params[param] )

            displ += ' ' + stage_name+'='+self.params[stage_name]
            displ += '('+','.join( pL )+')'

        return displ

    def computeID(self, compress_stage=False):
        ""
        lst = [ self.filepath, self.name ]
        lst.extend( self._get_parameters_as_list( compress_stage ) )
        return tuple( lst )

    def _get_parameters_as_list(self, compress_stage):
        ""
        L = []
        if len( self.params ) > 0:
            for n,v in self.params.items():
                if self._hide_parameter( n, compress_stage ):
                    pass
                elif self._compress_parameter( n, compress_stage ):
                    L.append( n )
                else:
                    L.append( n + '=' + v )
            L.sort()

        return L

    def _hide_parameter(self, param_name, compress_stage):
        ""
        if compress_stage and self.staged:
            return param_name == self.staged[0]
        return False

    def _compress_parameter(self, param_name, compress_stage):
        ""
        if compress_stage and self.staged:
            if param_name in self.staged[1:]:
                return True
        return False

    def _compute_shortened_name(self, fullname):
        ""
        if self.short and len(fullname) > self.short:
            hsh = _compute_hash( fullname )[:10]
            return self.name[:20] + '.' + hsh
        else:
            return fullname


if sys.version_info[0] < 3:
    def _compute_hash( astring ):
        ""
        return hashlib.sha1(astring).hexdigest()
else:
    def _compute_hash( astring ):
        ""
        return hashlib.sha1( astring.encode() ).hexdigest()
