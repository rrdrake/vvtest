#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.


class ResourcePool:

    def __init__(self, total, maxavail):
        ""
        self.total = total
        self.maxavail = maxavail

        self.pool = None  # maps hardware id to num available

    def maxAvailable(self):
        ""
        return self.maxavail

    def numTotal(self):
        ""
        return self.total

    def numAvailable(self):
        ""
        if self.pool == None:
            num = self.total
        else:
            num = 0
            for cnt in self.pool.values():
                num += max( 0, cnt )

        return num

    def get(self, num):
        ""
        items = []

        if num > 0:

            if self.pool == None:
                self._initialize_pool()

            while len(items) < num:
                self._get_most_available( items, num )

        return items

    def put(self, items):
        ""
        for idx in items:
            self.pool[idx] = ( self.pool[idx] + 1 )

    def _get_most_available(self, items, num):
        ""
        # reverse the index in the sort list (want indexes to be ascending)
        L = [ (cnt,self.maxavail-idx) for idx,cnt in self.pool.items() ]
        L.sort( reverse=True )

        for cnt,ridx in L:
            idx = self.maxavail - ridx
            items.append( idx )
            self.pool[idx] = ( self.pool[idx] - 1 )
            if len(items) == num:
                break

    def _initialize_pool(self):
        ""
        self.pool = {}

        for i in range(self.total):
            idx = i%(self.maxavail)
            self.pool[idx] = self.pool.get( idx, 0 ) + 1
