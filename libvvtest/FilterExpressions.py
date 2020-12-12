#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
import re
import fnmatch

try:
    from teststatus import RESULTS_KEYWORDS
except ImportError:
    from .teststatus import RESULTS_KEYWORDS


class WordExpression:
    """
    Takes a string consisting of words, parentheses, and the operators "and",
    "or", and "not".  A word is any sequence of characters not containing
    a space or a parenthesis except the special words "and", "or", and "not".
    The initial string is parsed during construction then later evaluated
    with the evaluate() method.  Each word is evaluated to true or false
    based on an evaluator function given to the evaluate() method.

    Without an expression (a None), the evaluate method will always return
    True, while an empty string for an expression will always evaluate to
    False.
    """

    def __init__(self, expr=None):
        ""
        self.expr = None

        self.words = set()   # the words in the expression

        self.evalexpr = None

        if expr != None:
            self.append( expr )

    def getExpression(self):
        ""
        return self.expr

    def append(self, expr, magic_do_nr=True):
        """
        Extends the given expression string using the AND operator.
        """
        if expr != None:

            expr = expr.strip()

            if self.expr != None:
                expr = combine_two_expressions( self.expr, expr )

            self.expr = expr

            self.evalexpr = self.create_eval_expression( self.expr, self.words )

    def create_eval_expression(self, string_expr, wordset):
        ""
        return parse_word_expression( string_expr, wordset )

    def getWordList(self):
        """
        Returns a list containing the words in the current expression.
        """
        return list( self.words )

    def keywordEvaluate(self, keyword_list):
        """
        Returns the evaluation of the expression against a simple keyword list.
        """
        return self.evaluate( lambda k: k in keyword_list )

    def evaluate(self, evaluator_func):
        """
        Evaluates the expression from left to right using the given
        'evaluator_func' to evaluate True/False of each word.  If the original
        expression string is empty, false is returned.  If no expression was
        set in this object, true is returned.
        """
        if self.evalexpr == None:
            return True

        def evalfunc(tok):
            if evaluator_func(tok): return True
            return False

        r = eval( self.evalexpr )

        return r

    def __repr__(self):
        if self.expr == None:return 'WordExpression=None'
        return 'WordExpression="' + self.expr + '"'

    def __str__(self): return self.__repr__()


class NonResultsWordExpression( WordExpression ):

    def create_eval_expression(self, string_expr, wordset):
        ""
        return parse_non_results_expression( string_expr, wordset )

    def containsResultsKeywords(self):
        ""
        return len( set( RESULTS_KEYWORDS ).intersection( self.words ) ) > 0


def combine_two_expressions( expr1, expr2 ):
    ""
    if expr1 and expr2:
        expr = expr1 + ' and ' + conditional_paren_wrap( expr2 )
    else:
        # one expression is empty, which is always false,
        # so replace the whole thing with an empty expr
        expr = ''

    return expr


def conditional_paren_wrap( expr ):
    ""
    if expr:
        expr = expr.strip()
        px = parenthetical_tokenize( expr )
        if px.numTokens() > 1:
            return '( '+expr+' )'

    return expr


class ParenExpr:

    def __init__(self):
        ""
        self.toks = []

    def parse(self, toklist, tok_idx):
        ""
        while tok_idx < len(toklist):
            tok = toklist[tok_idx]
            tok_idx += 1

            if tok == '(':
                sub = ParenExpr()
                self.toks.append( sub )
                tok_idx = sub.parse( toklist, tok_idx )
            elif tok == ')':
                break
            else:
                self.toks.append( tok )

        return tok_idx

    def numTokens(self): return len( self.toks )


def parenthetical_tokenize( expr ):
    """
    Parse the given expression into a single ParenExpr object. Each ParenExpr
    contains a list of string tokens and ParenExpr objects (which are created
    when a paren is encountered.
    """
    assert expr and expr.strip()

    toklist = separate_expression_into_tokens( expr )
    px = ParenExpr()
    px.parse( toklist, 0 )

    return px


def parse_word_expression( expr, wordset ):
    """
    Throws a ValueError if the string is an invalid expression.
    Returns the final expression string (which may be modified from the
    original).
    """
    if wordset != None:
        wordset.clear()

    toklist = separate_expression_into_tokens( expr )
    evalexpr = convert_token_list_into_eval_string( toklist )

    add_words_to_set( toklist, wordset )

    def evalfunc(tok):
        return True
    try:
        # evaluate the expression to test validity
        v = eval( evalexpr )
        assert type(v) == type(False)
    except Exception:
        raise ValueError( 'invalid option expression: "' + expr + '"' )

    return evalexpr


def parse_non_results_expression( expr, wordset=None ):
    ""
    nrmod = NonResultsExpressionModifier( expr, wordset )
    toklist = nrmod.getNonResultsTokenList()

    if len( toklist ) == 0:
        return None
    else:
        evalexpr = convert_token_list_into_eval_string( toklist )
        return evalexpr


class NonResultsExpressionModifier:

    def __init__(self, expr, wordset):
        ""
        self.toklist = separate_expression_into_tokens( expr )
        add_words_to_set( self.toklist, wordset )

        self.toki = 0

        self.nonresults_toklist = self.parse_subexpr()

        trim_leading_binary_operator( self.nonresults_toklist )

    def getNonResultsTokenList(self):
        ""
        return self.nonresults_toklist

    def parse_subexpr(self):
        ""
        toklist = []
        oplist = []

        while self.toki < len( self.toklist ):

            tok = self.toklist[ self.toki ]
            self.toki += 1

            if tok in _OPERATOR_LIST:
                if tok == ')':
                    break
                elif tok == '(':
                    sublist = self.parse_subexpr()
                    if sublist:
                        append_sublist( toklist, oplist, sublist )
                    oplist = []
                else:
                    oplist.append( tok )

            elif tok in RESULTS_KEYWORDS:
                oplist = []

            else:
                append_token( toklist, oplist, tok )
                oplist = []

        return toklist


def trim_leading_binary_operator( toklist ):
    ""
    if toklist:
        if toklist[0] == 'and' or toklist[0] == 'or':
            toklist.pop( 0 )


def append_sublist( toklist, oplist, sublist ):
    ""
    append_operator( toklist, oplist )

    if oplist and len( sublist ) > 1:
        sublist = ['(']+sublist+[')']

    toklist.extend( sublist )


def append_token( toklist, oplist, tok ):
    ""
    append_operator( toklist, oplist )
    toklist.append( tok )


def append_operator( toklist, oplist ):
    ""
    if oplist:
        toklist.extend( oplist )


_OPERATOR_LIST = ['(',')','not','and','or']

def convert_token_list_into_eval_string( toklist ):
    ""
    modified_toklist = []

    for tok in toklist:
        if tok in _OPERATOR_LIST:
            modified_toklist.append( tok )
        elif tok:
            modified_toklist.append( '(evalfunc("'+tok+'")==True)' )
        else:
            modified_toklist.append( 'False' )

    return ' '.join( modified_toklist )


def add_words_to_set( toklist, wordset ):
    ""
    if wordset != None:
        for tok in toklist:
            if tok and tok not in _OPERATOR_LIST:
                wordset.add( tok )


def separate_expression_into_tokens( expr ):
    ""
    toklist = []

    if expr.strip():

        for whitetok in expr.strip().split():
            for lptok in split_but_retain_separator( whitetok, '(' ):
                for rptok in split_but_retain_separator( lptok, ')' ):
                    rptok = rptok.strip()
                    if rptok == '!':
                        toklist.append( 'not' )
                    elif rptok:
                        if rptok.startswith('!'):
                            toklist.append( 'not' )
                            toklist.append( rptok[1:] )
                        else:
                            toklist.append( rptok )

    else:
        toklist.append( '' )

    return toklist


def split_but_retain_separator( expr, separator ):
    ""
    seplist = []

    splitlist = list( expr.split( separator ) )
    last_token = len(splitlist) - 1

    for i,tok in enumerate( splitlist ):
        seplist.append( tok )
        if i < last_token:
            seplist.append( separator )

    return seplist


def replace_forward_slashes( expr, negate=False ):
    """
    Convert a simple expression with forward slashes '/' to one with
    operator "or"s instead.

        "A/B" -> "A or B"
        "A/B/!C" -> "A or B or !C"
        "A/B" with negate=True -> "not A or not B"

    A ValueError is raised if both '/' and a paren is in the expression, or
    if '/' and the operators "and" or "or" are in the expression.
    """
    if '/' in expr:
        if '(' in expr or ')' in expr:
            raise ValueError( 'a "/" and parenthesis cannot be in the '
                              'same expression: '+repr(expr) )

        rtnL = []
        for tok in expr.strip().split('/'):
            tok = tok.strip()
            if tok:

                sL = tok.split()
                if 'and' in sL or 'or' in sL or 'not' in sL:
                    raise ValueError( 'a "/" and a boolean operator '
                                      '("and" "or" "not") cannot be in the '
                                      'same expression: '+repr(expr) )

                if negate:
                    rtnL.append( 'not '+tok )
                else:
                    rtnL.append( tok )

        return ' or '.join( rtnL )

    elif negate:
        return 'not '+conditional_paren_wrap( expr )

    else:
        return expr


def join_expressions_with_AND( expr_list ):
    ""
    final = None

    for expr in expr_list:
        expr = expr.strip()

        if expr:
            if len(expr_list) > 1:
                expr = conditional_paren_wrap( expr )

            if final is None:
                final = expr
            else:
                final = final + ' and ' + expr

        else:
            # because empty expressions evaluate to False, the entire
            # expression will always evaluate to False
            return ''

    return final


def create_word_expression( word_expr_list, not_word_expr_list ):
    ""
    exprL = []

    if word_expr_list:
        for expr in word_expr_list:
            exprL.append( clean_up_word_expression(expr) )

    if not_word_expr_list:
        for expr in not_word_expr_list:
            exprL.append( clean_up_word_expression( expr, negate=True ) )

    if len( exprL ) > 0:
        return WordExpression( join_expressions_with_AND( exprL ) )

    return None


def clean_up_word_expression( expr, negate=False ):
    ""
    ex = replace_forward_slashes( expr, negate )

    wx = WordExpression( ex )

    # magic: would like this check to be in the WordExpression class
    for wrd in wx.getWordList():
        if not allowable_word( wrd ):
            raise ValueError( 'invalid word: "'+str(wrd)+'"' )

    return ex


allowable_chars = set( 'abcdefghijklmnopqrstuvwxyz' + \
                       'ABCDEFGHIJKLMNOPQRSTUVWXYZ' + \
                       '0123456789_' + '-+=#@%^:.~' )

def allowable_word(s):
    ""
    return set(s).issubset( allowable_chars )


##############################################################################

class ParamFilter:

    def __init__(self, *expr):
        """
        If 'expr' is not None, load() is called.
        """
        self.wexpr = None
        self.wordD = {}
        if len( expr ) > 0:
            self.load(expr)

    def load(self, expr_list):
        """
        Loads the parameter specifications.  The 'expr' argument can be either
        a string word expression or a list of strings.

        If a list, each string is composed of parameter specifications
        separated by a '/' character.  A parameter specification is of the
        form:

            np        parameter np is defined
            np=       same as "np"
            !np       parameter np is not defined
            np!=      same as "!np"
            np<=4     parameter is less than or equal to four
            np>=4     parameter is greater than or equal to four
            np<4      parameter is less than four
            np>4      parameter is greater than four
            !np=4     not parameter is equal to four

        The parameter specifications separated by '/' are OR'ed together and
        the list entries are AND'ed together.

        Raises a ValueError if the expression contains a syntax error.
        """
        self.wexpr = WordExpression()
        for expr in expr_list:
            self.wexpr.append( expr )

        # map each word that appears to be an evaluation function object instance
        self.wordD = {}
        for w in self.wexpr.getWordList():
            self.wordD[w] = self._make_func(w)

    def evaluate(self, paramD):
        """
        Evaluate the expression previously loaded against the given parameter
        values.  Returns true or false.
        """
        if self.wexpr == None:
            return 1
        evalobj = ParamFilter.Evaluator(self.wordD, paramD)
        return self.wexpr.evaluate( evalobj.evaluate )

    class Evaluator:
        def __init__(self, wordD, paramD):
            self.wordD = wordD
            self.paramD = paramD
        def evaluate(self, word):
            return self.wordD[word].evaluate(self.paramD)

    def _make_func(self, word):
        """
        Returns an instance of an evaluation class based on the word.
        """
        if not word: raise ValueError( 'empty word (expected a word)' )
        if word[0] == '!':
            f = self._make_func( word[1:] )
            f.negate = not f.negate
            return f
        L = word.split( '<=', 1 )
        if len(L) > 1:
            if not L[1]: raise ValueError( "empty less-equal value" )
            return EvalLE( L[0], L[1] )
        L = word.split( '>=', 1 )
        if len(L) > 1:
            if not L[1]: raise ValueError( "empty greater-equal value" )
            return EvalGE( L[0], L[1] )
        L = word.split( '!=', 1 )
        if len(L) > 1:
            return EvalNE( L[0], L[1] )
        L = word.split( '<', 1 )
        if len(L) > 1:
            if not L[1]: raise ValueError( "empty less-than value" )
            return EvalLT( L[0], L[1] )
        L = word.split( '>', 1 )
        if len(L) > 1:
            if not L[1]: raise ValueError( "empty greater-than value" )
            return EvalGT( L[0], L[1] )
        L = word.split( '=', 1 )
        if len(L) > 1:
            return EvalEQ( L[0], L[1] )
        return EvalEQ( word, '' )


class EvalOperator:
    def __init__(self, param, value):
        if not param: raise ValueError( 'parameter name is empty' )
        self.p = param ; self.v = value
        self.negate = False
    def evaluate(self, paramD):
        b = self._eval_expr( paramD )
        if self.negate: b = not b
        return b


class EvalEQ( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if self.v:
            if v == None: return 0  # paramD does not have the parameter
            if type(v) == type(2): return v == int(self.v)
            elif type(v) == type(2.2): return v == float(self.v)
            if v == self.v: return 1
            try:
                if int(v) == int(self.v): return 1
            except Exception: pass
            try:
                if float(v) == float(self.v): return 1
            except Exception: pass
            return 0
        return v != None  # true if paramD has the parameter name

class EvalNE( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if self.v:
            if v == None: return 0  # paramD does not have the parameter
            if type(v) == type(2): return v != int(self.v)
            elif type(v) == type(2.2): return v != float(self.v)
            if v == self.v: return 0
            try:
                if int(v) == int(self.v): return 0
            except Exception: pass
            try:
                if float(v) == float(self.v): return 0
            except Exception: pass
            return 1
        return v == None  # true if paramD does not have the parameter name

class EvalLE( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if v == None: return 0
        if type(v) == type(2): return v <= int(self.v)
        elif type(v) == type(2.2): return v <= float(self.v)
        if v == self.v: return 1
        try:
            if int(v) > int(self.v): return 0
            return 1
        except Exception: pass
        try:
            if float(v) > float(self.v): return 0
            return 1
        except Exception: pass
        return v <= self.v

class EvalGE( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if v == None: return 0
        if type(v) == type(2): return v >= int(self.v)
        elif type(v) == type(2.2): return v >= float(self.v)
        if v == self.v: return 1
        try:
            if int(v) < int(self.v): return 0
            return 1
        except Exception: pass
        try:
            if float(v) < float(self.v): return 0
            return 1
        except Exception: pass
        return v >= self.v

class EvalLT( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if v == None: return 0
        if type(v) == type(2): return v < int(self.v)
        elif type(v) == type(2.2): return v < float(self.v)
        if v == self.v: return 0
        try:
            if int(v) >= int(self.v): return 0
            return 1
        except Exception: pass
        try:
            if not float(v) < float(self.v): return 0
            return 1
        except Exception: pass
        return v < self.v

class EvalGT( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if v == None: return 0
        if type(v) == type(2): return v > int(self.v)
        elif type(v) == type(2.2): return v > float(self.v)
        if v == self.v: return 0
        try:
            if int(v) <= int(self.v): return 0
            return 1
        except Exception: pass
        try:
            if not float(v) > float(self.v): return 0
            return 1
        except Exception: pass
        return v > self.v


def create_parameter_filter( param_expr_list, not_param_expr_list ):
    ""
    # construction will check validity

    exprL = []

    if param_expr_list:
        for expr in param_expr_list:
            ex = replace_forward_slashes( expr )
            ParamFilter( ex )
            exprL.append( ex )

    if not_param_expr_list:
        for expr in not_param_expr_list:
            ex = replace_forward_slashes( expr, negate=True )
            ParamFilter( ex )
            exprL.append( ex )

    if len( exprL ) > 0:
        return ParamFilter( join_expressions_with_AND( exprL ) )

    return None


######################################################################

if __name__ == "__main__":

    # this component is called as a 

    import getopt
    optL,argL = getopt.getopt( sys.argv[1:], "p:o:f:" )
    for n,v in optL:
        if n == '-p':
            pD = {}
            for param,value in [ s.split('/') for s in argL[0].split() ]:
                pD[param] = value
            pf = ParamFilter( v )
            if pf.evaluate( pD ):
                sys.stdout.write( 'true' )
            else:
                sys.stdout.write( 'false' )
            break

        elif n == '-f':
            wx = WordExpression( v )
            if wx.evaluate( lambda wrd: wrd == argL[0] ):
                sys.stdout.write( 'true' )
            else:
                sys.stdout.write( 'false' )
            break

        elif n == '-o':
            opts = argL[0].split()
            wx = WordExpression( v )
            if wx.evaluate( opts.count ):
                sys.stdout.write( 'true' )
            else:
                sys.stdout.write( 'false' )
            break

