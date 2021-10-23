#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import dirname, normpath
from os.path import join as pjoin

import hashlib

DEFAULT_MAX_NAME_LENGTH = 100


class TestID:

    def __init__(self, testname, filepath, params, staged_names, idtraits={}):
        ""
        self.name = testname
        self.filepath = filepath
        self.params = params
        self.staged = staged_names
        self.idtraits = idtraits

    def computeExecuteDirectory(self, shorten=True):
        ""
        bname = self.name

        paramL = self._get_parameters_as_list( compress_stage=True )
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

            if len(L) == 0:
                # can only happen with minxdirs; it is a bit of a hack, but
                # a single empty string will result in an execute directory
                # that is distinguishable from an analyze test
                L.append('')

        return L

    def _hide_parameter(self, param_name, compress_stage):
        ""
        if param_name in self.idtraits.get('minxdirs',[]):
            return True
        elif compress_stage and self.staged:
            return param_name == self.staged[0]
        else:
            return False

    def _compress_parameter(self, param_name, compress_stage):
        ""
        if compress_stage and self.staged:
            if param_name in self.staged[1:]:
                return True
        return False

    def _compute_shortened_name(self, fullname):
        ""
        nchar = self.idtraits.get( 'numchars', DEFAULT_MAX_NAME_LENGTH )

        if nchar and len(fullname) > nchar:
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
