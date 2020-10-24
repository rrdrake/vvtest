#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
import time
import datetime


daysofweek = set( 'mon tue wed thu fri sat sun'.split() )
daysofweekL = 'mon tue wed thu fri sat sun'.split()


def parse_num_seconds( value, round_to_int=False, negatives=False ):
    """
    Parse a string to num seconds. The string can be an integer or floating
    point number, or format HH:MM:SS, or 3d 10h 26m 10s. A value of None
    just returns None. A plain Exception is raised on error.

    'round' True means make the value an integer if parsed as a float
    'negatives' True means allow negative number of seconds
    """
    val = None

    if value != None:

        value = value.strip()
        if not value:
            raise Exception( 'empty string not allowed' )

        nval,err = parse_number( value )
        if err:
            if ':' in value:
                nval = parse_HH_MM_SS_to_seconds( value )
            else:
                nval = parse_h_m_s_to_seconds( value )

        if not negatives and nval < 0:
            raise Exception( 'cannot be negative: '+repr(value) )
        if round_to_int:
            nval = int( float(nval) + 0.5 )
        val = nval

    return val


def upcoming_time( specification, skip_num_days=0, timevalue=None ):
    """
    Parse a time specification string into num seconds (epoch time), such as
    "5pm" or "13:00".  The next upcoming time of the specification is assumed.

    If 'skip_num_days' is non-zero, then that number of days is added to the
    next upcoming time.  For example "5pm" with 'skip_num_days=1' will be
    24 hours past this coming 5pm.

    If 'timevalue' is None, then the current time is used, time.time().  If
    not None, it should be a number of seconds since epoch.
    """
    if timevalue == None:
        tm = datetime.datetime.now()
    else:
        tm = datetime.datetime.fromtimestamp( timevalue )

    h,m,s = hours_minutes_seconds( specification )

    tspec = tm.replace( hour=h, minute=m, second=s )

    oneday = datetime.timedelta(1)

    if tspec < tm:
        # the hour,minute,second specification is in the past
        tspec = tspec + oneday

    if skip_num_days != 0:
        tspec = tspec + skip_num_days * oneday
    
    return time.mktime( tspec.timetuple() )


def seconds_since_midnight( time_spec ):
    """
    Interprets the argument as a time of day specification.  The 'time_spec'
    can be a number between zero and 24 or a string containing am, pm, and
    colons (such as "3pm" or "21:30").  If the interpretation fails, an
    exception is raised.  Returns the number of seconds since midnight.
    """
    orig = time_spec

    try:
        if type(time_spec) == type(''):

            assert '-' not in time_spec
            
            ampm = None
            time_spec = time_spec.strip()
            if time_spec[-2:].lower() == 'am':
              ampm = "am"
              time_spec = time_spec[:-2]
            elif time_spec[-2:].lower() == 'pm':
              ampm = "pm"
              time_spec = time_spec[:-2]
            elif time_spec[-1:].lower() == 'a':
              ampm = "am"
              time_spec = time_spec[:-1]
            elif time_spec[-1:].lower() == 'p':
              ampm = "pm"
              time_spec = time_spec[:-1]
            
            L = [ s.strip() for s in time_spec.split(':') ]
            assert len(L) == 1 or len(L) == 2 or len(L) == 3
            L2 = [ int(i) for i in L ]
            
            hr = L2[0]
            mn = 0
            sc = 0
            
            if ampm:
                if ampm == 'am':
                    if hr == 12:
                        hr = 0
                    else:
                        assert hr < 12
                else:
                    if hr == 12:
                        hr = 12
                    else:
                        assert hr < 12
                        hr += 12
            else:
                assert hr < 24
            
            if len(L2) > 1:
                mn = L2[1]
                assert mn < 60
            
            if len(L2) > 2:
                sc = L2[2]
                assert sc < 60

            nsecs = hr*60*60 + mn*60 + sc
              
        else:
            # assume number of hours since midnight
            assert not time_spec < 0 and time_spec < 24
            nsecs = int(time_spec)*60*60

    except Exception:
        raise Exception( "invalid time-of-day specification: "+str(orig) )

    return nsecs


def hours_minutes_seconds( time_spec ):
    """
    Interprets a string argument as a time of day specification and returns
    a string "hh:mm:ss" in 24 hour clock.  The string can contain am, pm, and
    colons, such as "3pm" or "21:30".  If the interpretation fails, an
    exception is raised.
    """
    orig = time_spec

    try:

        assert '-' not in time_spec

        ampm = None
        time_spec = time_spec.strip()
        if time_spec[-2:].lower() == 'am':
          ampm = "am"
          time_spec = time_spec[:-2]
        elif time_spec[-2:].lower() == 'pm':
          ampm = "pm"
          time_spec = time_spec[:-2]
        elif time_spec[-1:].lower() == 'a':
          ampm = "am"
          time_spec = time_spec[:-1]
        elif time_spec[-1:].lower() == 'p':
          ampm = "pm"
          time_spec = time_spec[:-1]

        L = [ s.strip() for s in time_spec.split(':') ]
        assert len(L) == 1 or len(L) == 2 or len(L) == 3
        L2 = [ int(i) for i in L ]

        hr = L2[0]
        if ampm:
            if ampm == 'am':
                if hr == 12:
                    hr = 0
                else:
                    assert hr < 12
            else:
                if hr == 12:
                    hr = 12
                else:
                    assert hr < 12
                    hr += 12
        else:
            assert hr < 24
        
        mn = 0
        if len(L2) > 1:
            mn = L2[1]
            assert mn < 60
        
        sc = 0
        if len(L2) > 2:
            sc = L2[2]
            assert sc < 60

    except Exception:
        raise Exception( "invalid time-of-day specification: "+str(orig) )

    return hr,mn,sc


def chop_midnight( tsecs ):
    """
    Returns the epoch time at midnight for the given day.
    """
    tup = time.localtime( tsecs )
    tup = ( tup[0], tup[1], tup[2], 0, 0, 0, tup[6], tup[7], tup[8] )
    return int( time.mktime( tup ) + 0.5 )


def chop_hour( tsecs ):
    """
    Returns the epoch time at the most recent hour for the given time.
    """
    tup = time.localtime( tsecs )
    tup = ( tup[0], tup[1], tup[2], tup[3], 0, 0, tup[6], tup[7], tup[8] )
    return int( time.mktime( tup ) + 0.5 )


def day_of_week( tsecs ):
    """
    Returns the day of the week for the given day, in lower case and first
    three letters.
    """
    tup = time.localtime( tsecs )
    return daysofweekL[ tup[6] ]


def first_day_of_month( tsecs ):
    """
    Returns the epoch time at midnight of the first day of the month.
    """
    for i in range(40):
        tup = time.localtime( tsecs )
        if tup[2] == 1:
            # found first day of the month; now chop to midnight
            return chop_midnight( tsecs )
        tsecs -= 24*60*60

    raise Exception( 'the algorithm failed' )


def next_day_of_week( dow, tsecs ):
    """
    Returns the epoch time at midnight of the next 'dow' day of the week.
    """
    for i in range(40):
        tup = time.localtime( tsecs )
        if dow == daysofweekL[ tup[6] ]:
            # found first upcoming day; now chop to midnight
            return chop_midnight( tsecs )
        tsecs += 24*60*60

    raise Exception( 'the algorithm failed' )


def parse_h_m_s_to_seconds( value ):
    """
    such as "17s" or "2h 10m 30s"
    """
    sumval = 0

    for tok in value.split():
        if tok.endswith('s'):
            n,e = parse_number( tok[:-1] )
            if e:
                raise Exception( 'could not parse to seconds: '+repr(value) )
            sumval += n
        elif tok.endswith('m'):
            n,e = parse_number( tok[:-1] )
            if e:
                raise Exception( 'could not parse to seconds: '+repr(value) )
            sumval += ( n * 60 )
        elif tok.endswith('h'):
            n,e = parse_number( tok[:-1] )
            if e:
                raise Exception( 'could not parse to seconds: '+repr(value) )
            sumval += ( n * 60*60 )
        elif tok.endswith('d'):
            n,e = parse_number( tok[:-1] )
            if e:
                raise Exception( 'could not parse to seconds: '+repr(value) )
            sumval += ( n * 24*60*60 )
        else:
            raise Exception( 'could not parse to seconds: '+repr(value) )

    return sumval


def parse_HH_MM_SS_to_seconds( value ):
    ""
    if not value.strip():
        raise Exception( 'empty string not allowed' )

    sL = value.strip().split(':')

    sumval = 0

    n,e = parse_number( sL[-1] )
    if e or n < 0 or ( ':' in value and n >= 60 ):
        raise Exception( 'invalid HH:MM:SS specification: '+repr(value) )
    sumval += n

    if len(sL) > 1:
        n,e = parse_integer( sL[-2] )
        if e or n < 0 or n >= 60:
            raise Exception( 'invalid HH:MM:SS specification: '+repr(value) )
        sumval += ( n * 60 )

    if len(sL) > 2:
        n,e = parse_integer( sL[-3] )
        if e or n < 0:
            raise Exception( 'invalid HH:MM:SS specification: '+repr(value) )
        sumval += ( n * 60*60 )

    return sumval


def parse_number( value ):
    ""
    val = None
    err = ''

    if value != None:
        try:
            ival = int(value)
        except Exception:
            try:
                fval = float(value)
            except Exception:
                err = 'could not cast to a number: '+repr(value)
            else:
                val = fval
        else:
            val = ival

    return val,err


def parse_integer( value ):
    ""
    val = None
    err = ''

    if value != None:
        try:
            ival = int(value)
        except Exception:
            err = 'could not cast to an integer: '+repr(value)
        else:
            val = ival

    return val,err
