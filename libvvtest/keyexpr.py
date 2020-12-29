#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.


from .wordexpr import WordExpression
from .wordexpr import convert_token_list_into_eval_string
from .wordexpr import separate_expression_into_tokens
from .wordexpr import add_words_to_set
from .wordexpr import clean_up_word_expression
from .wordexpr import join_expressions_with_AND
from .wordexpr import TokenTree, prune_token_tree, collect_token_list_from_tree

from .teststatus import RESULTS_KEYWORDS
RESULTS_KEYWORD_SET = set( RESULTS_KEYWORDS )


def create_keyword_expression( word_expr_list, not_word_expr_list ):
    ""
    exprL = []

    if word_expr_list:
        for expr in word_expr_list:
            exprL.append( clean_up_word_expression(expr) )

    if not_word_expr_list:
        for expr in not_word_expr_list:
            exprL.append( clean_up_word_expression( expr, negate=True ) )

    if len( exprL ) > 0:
        return KeywordExpression( join_expressions_with_AND( exprL ) )

    return None


class KeywordExpression( WordExpression ):

    def evaluate(self, keyword_list):
        ""
        return WordExpression.evaluate( self, keyword_list )


class NonResultsKeywordExpression( KeywordExpression ):

    def _create_eval_expression(self, string_expr, wordset):
        ""
        return parse_non_results_expression( string_expr, wordset )

    def containsResultsKeywords(self):
        ""
        return len( RESULTS_KEYWORD_SET.intersection( self.words ) ) > 0


def parse_non_results_expression( expr, wordset=None ):
    ""
    toklist = separate_expression_into_tokens( expr )
    add_words_to_set( toklist, wordset )

    new_toklist = remove_results_keywords( toklist )

    if len( new_toklist ) == 0:
        return None
    else:
        evalexpr = convert_token_list_into_eval_string( new_toklist )
        return evalexpr


def remove_results_keywords( toklist ):
    ""
    tree = TokenTree()
    tree.parse( toklist, 0 )

    while apply_pruning_operations( tree ) > 0:
        pass

    toks = []
    collect_token_list_from_tree( tree, toks )

    return toks


def is_results_token( tok ):
    ""
    return tok in RESULTS_KEYWORD_SET


def is_empty_subtree( tok ):
    ""
    return isinstance( tok, TokenTree ) and tok.numTokens() == 0


def apply_pruning_operations( tree ):
    ""
    cnt =  prune_token_tree( tree, is_results_token )
    cnt += prune_token_tree( tree, is_empty_subtree )
    return cnt
