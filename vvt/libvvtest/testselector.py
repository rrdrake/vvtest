#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys

from . import pathutil


class TestSelector:

    def __init__(self, test_dir, testfilter, creator):
        ""
        self.tfilter = testfilter
        self.creator = creator

        self._set_filter_dir( test_dir, os.getcwd() )

    def applyPermanentFilters(self, tlist):
        ""
        groups = tlist.createAnalyzeGroupMap()

        self.tfilter.applyPermanent( tlist.getTestMap() )

        for analyze, tcaseL in groups.iterateGroups():
            self.tfilter.checkAnalyze( analyze, tcaseL )

        tlist.countActive()

    def prepareActiveTests(self, tlist, apply_filters=True,
                                        remove_new_skips=False):
        """
        If 'remove_new_skips' is True then every test skipped by the current
        filtering is removed entirely from the test list, but skips from a
        previous run are retained.
        """
        tlist.createAnalyzeGroupMap()

        if apply_filters:
            self._apply_filters( tlist, remove_new_skips=remove_new_skips )

        self._refresh_active_tests( tlist )

        tlist.countActive()

    def prepareBaselineTests(self, tlist):
        ""
        tlist.createAnalyzeGroupMap()

        self._apply_filters( tlist )

        self._refresh_active_tests( tlist )

        self.tfilter.applyBaselineSkips( tlist.getTestMap() )

        tlist.countActive()

    def _apply_filters(self, tlist, remove_new_skips=False):
        ""
        tcasemap = tlist.getTestMap()
        groups = tlist.getGroupMap()

        self.tfilter.applyRuntime( tcasemap, self.filterdir,
                                   force_checks=remove_new_skips )

        for analyze, tcaseL in groups.iterateGroups():
            self.tfilter.checkAnalyze( analyze, tcaseL )

        if remove_new_skips:
            self.tfilter.removeNewSkips( tcasemap )

    def _refresh_active_tests(self, tlist):
        ""
        tspecs = [ tcase.getSpec() for tcase in tlist.getActiveTests() ]
        self.creator.reparseTests( tspecs )

    def _set_filter_dir(self, test_dir, cwd):
        """
        If the current working directory is a subdir of an existing test
        results directory, then this function sets the filter directory to
        the relative path from the top of the test results directory to the
        current working directory.
        """
        if pathutil.is_subdir( test_dir, cwd ):
            d = pathutil.compute_relative_path( test_dir, cwd )
            self.filterdir = d
        else:
            self.filterdir = None
