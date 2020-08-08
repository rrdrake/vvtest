#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os
import sys
import time
from os.path import join as pjoin


class BatchFileNamer:

    def __init__(self, rootdir, basename="testlist"):
        ""
        self.rootdir = rootdir
        self.basename = basename

    def getRootDir(self):
        ""
        return self.rootdir

    def getFilePath(self, batchid=None):
        ""
        if batchid == None:
            return pjoin( self.rootdir, self.basename )
        else:
            return self._get_batch_path( batchid, self.basename )

    def getScriptPath(self, batchid):
        ""
        pn = self._get_batch_path( batchid, 'qbat' )
        return pjoin( self.rootdir, pn )

    def getOutputPath(self, batchid):
        ""
        pn = self._get_batch_path( batchid, 'qbat-out' )
        return pjoin( self.rootdir, pn )

    def getBatchPath(self, batchid):
        """
        Given a base file name and a batch id, this function returns the
        file name in the batchset subdirectory and with the id appended.
        """
        pn = self._get_batch_path( batchid, self.basename )
        return pjoin( self.rootdir, pn )

    def _get_batch_dir(self, batchid):
        """
        Given a queue/batch id, this function returns the corresponding
        subdirectory name.
        """
        return 'batchset' + str( int( float(batchid)/50 + 0.5 ) )

    def _get_batch_path(self, batchid, basename):
        ""
        subd = self._get_batch_dir( batchid )
        return pjoin( subd, basename+'.'+str(batchid) )

    def globBatchDirectories(self):
        """
        Returns a list of existing batch working directories.
        """
        dL = []
        for f in os.listdir( self.rootdir ):
            if f.startswith( 'batchset' ):
                dL.append( pjoin( self.rootdir, f ) )
        return dL
