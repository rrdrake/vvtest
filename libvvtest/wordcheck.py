#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.


allowable_variable_chars = set( 'abcdefghijklmnopqrstuvwxyz'
                                'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                                '0123456789_' )

allowable_word_chars = allowable_variable_chars.union( '.-=+#@^%:~' )

allowable_param_value_chars = allowable_word_chars.union( '<>!' )

allowable_wildcard_expression_chars = allowable_word_chars.union( '*?[]!' )


def allowable_word( word ):
    ""
    return set(word).issubset( allowable_word_chars )


def check_words( wordlist ):
    ""
    for word in wordlist:
        if not allowable_word( word ):
            raise ValueError( 'invalid word: '+repr(word) )


def allowable_variable( varname ):
    ""
    if not varname or varname[0] in '0123456789':
        return False
    return set(varname).issubset( allowable_variable_chars )


def check_variable_name( name ):
    ""
    if not allowable_variable( name ):
        raise ValueError( "invalid variable name: "+repr(name) )


def allowable_expression_word( word ):
    ""
    return set(word).issubset( allowable_word_chars )


def check_expression_words( wordlist ):
    ""
    for word in wordlist:
        if not allowable_expression_word( word ):
            raise ValueError( 'invalid expression word: '+repr(word) )


def allowable_wildcard_expression_word( word ):
    ""
    return set(word).issubset( allowable_wildcard_expression_chars )

def check_wildcard_expression_words( wordlist ):
    ""
    for word in wordlist:
        if not allowable_wildcard_expression_word( word ):
            raise ValueError( 'invalid wildcard expression word: '+repr(word) )


def allowable_param_value( word ):
    ""
    return set(word).issubset( allowable_param_value_chars )


def allowable_parameter_expr_word( word ):
    ""
    return set(word).issubset( allowable_word_chars )
