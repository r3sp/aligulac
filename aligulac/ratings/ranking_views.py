from django.shortcuts import render_to_response, get_object_or_404
from django.db.models import Q, Sum

from ratings.models import Earnings, Period, Player, Rating
from ratings.tools import (filter_active, total_ratings, count_matchup_games, count_mirror_games,
                            populate_teams, country_list, currency_list)

from aligulac.cache import cache_page
from aligulac.tools import Message, base_ctx, get_param
from aligulac.settings import INACTIVE_THRESHOLD

msg_preview = 'This is a <em>preview</em> of the next rating list. It will not be finalized until %s.'

# {{{ periods view
@cache_page
def periods(request):
    base = base_ctx('Ranking', 'History', request)
    base['periods'] = Period.objects.filter(computed=True).order_by('-id')
    return render_to_response('periods.html', base)
# }}}

# {{{ period view
@cache_page
def period(request, period_id):
    base = base_ctx('Ranking', 'Current', request)

    # {{{ Get period object
    period = get_object_or_404(Period, id=period_id, computed=True)
    if period.is_preview():
        base['messages'].append(Message(msg_preview % period.end.strftime('%B %d'), type=Message.INFO))

    base['period'] = period
    if period.id != base['curp'].id:
        base['curpage'] = ''
    # }}}

    # {{{ Best and most specialised players
    qset = total_ratings(filter_active(Rating.objects.filter(period=period)))
    base.update({
        'best':   qset.latest('rating'),
        'bestvp': qset.latest('tot_vp'),
        'bestvt': qset.latest('tot_vt'),
        'bestvz': qset.latest('tot_vz'),
        'specvp': qset.extra(select={'d':'rating_vp/dev_vp*rating'}).latest('d'),
        'specvt': qset.extra(select={'d':'rating_vt/dev_vt*rating'}).latest('d'),
        'specvz': qset.extra(select={'d':'rating_vz/dev_vz*rating'}).latest('d'),
    })
    # }}}

    # {{{ Matchup statistics
    qset = period.match_set
    base['pvt_wins'], base['pvt_loss'] = count_matchup_games(qset, 'P', 'T')
    base['pvz_wins'], base['pvz_loss'] = count_matchup_games(qset, 'P', 'Z')
    base['tvz_wins'], base['tvz_loss'] = count_matchup_games(qset, 'T', 'Z')
    base.update({
        'pvp_games': count_mirror_games(qset, 'P'),
        'tvt_games': count_mirror_games(qset, 'T'),
        'zvz_games': count_mirror_games(qset, 'Z'),
    })
    # }}}

    # {{{ Build country list
    all_players = Player.objects.filter(rating__period_id=period.id, rating__decay__lt=INACTIVE_THRESHOLD)
    base['countries'] = country_list(all_players)
    # }}}

    # {{{ Initial filtering of ratings
    entries = filter_active(period.rating_set).select_related('player')

    # Race filter
    race = get_param(request, 'race', 'ptzrs')
    q = Q()
    for r in race:
        q |= Q(player__race=r.upper())
    entries = entries.filter(q)

    # Country filter
    nats = get_param(request, 'nats', 'all')
    if nats == 'foreigners':
        entries = entries.exclude(player__country='KR')
    elif nats != 'all':
        entries = entries.filter(player__country=nats)

    # Sorting
    sort = get_param(request, 'sort', '')
    if sort not in ['vp', 'vt', 'vz']: 
        entries = entries.order_by('-rating', 'player__tag')
    else:
        entries = entries.extra(select={'d':'rating+rating_'+sort}).order_by('-d', 'player__tag')

    base.update({
        'race': race,
        'nats': nats,
        'sort': sort,
    })
    # }}}

    # {{{ Pages etc.
    pagesize = 40
    page = int(get_param(request, 'page', 1))
    nitems = entries.count()
    npages = nitems//pagesize + (1 if nitems % pagesize > 0 else 0)
    page = min(max(page, 1), npages)
    entries = entries[(page-1)*pagesize : page*pagesize]

    base.update({
        'page':       page,
        'npages':     npages,
        'startcount': (page-1)*pagesize,
        'entries':    populate_teams(entries),
        'nperiods':   Period.objects.filter(computed=True).count(),
    })
    # }}}

    base.update({
        'sortable':   True,
        'localcount': True,
    })
        
    return render_to_response('period.html', base)
# }}}

# {{{ earnings view
@cache_page
def earnings(request):
    base = base_ctx('Ranking', 'Earnings', request)

    # {{{ Build country and currency list
    all_players = Player.objects.filter(earnings__player__isnull=False).distinct()
    base['countries'] = country_list(all_players)
    base['currencies'] = currency_list(Earnings.objects)
    # }}}

    # {{{ Initial filtering of earnings
    preranking = Earnings.objects

    # Filtering by year
    year = get_param(request, 'year', 'all')
    if year != 'all':
        preranking = preranking.filter(event__latest__year=int(year))

    # Country filter
    nats = get_param(request, 'country', 'all')
    if nats == 'foreigners':
        preranking = preranking.exclude(player__country='KR')
    elif nats != 'all':
        preranking = preranking.filter(player__country=nats)

    # Currency filter
    curs = get_param(request, 'currency', 'all')
    if curs != 'all':
        preranking = preranking.filter(currency=curs)

    base['filters'] = {'year': year, 'country': nats, 'currency': curs}

    ranking = preranking.values('player')\
                        .annotate(totalorigearnings=Sum('origearnings'))\
                        .annotate(totalearnings=Sum('earnings'))\
                        .order_by('-totalearnings', 'player')
    # }}}

    # {{{ Calculate total earnings
    base.update({
        'totalorigprizepool': preranking.aggregate(Sum('origearnings'))['origearnings__sum'],
        'totalprizepool':     preranking.aggregate(Sum('earnings'))['earnings__sum'],
    })
    # }}}

    # {{{ Pages, etc.
    pagesize = 40
    page = int(get_param(request, 'page', 1))
    nitems = ranking.count()
    npages = nitems//pagesize + (1 if nitems % pagesize > 0 else 0)
    page = min(max(page, 1), npages)

    base.update({
        'page':       page,
        'npages':     npages,
        'startcount': (page-1)*pagesize,
    })

    if nitems > 0:
        ranking = ranking[(page-1)*pagesize : page*pagesize]
    else:
        base['empty'] = True
    # }}}

    # {{{ Populate with player and team objects
    ids = [p['player'] for p in ranking]
    players = Player.objects.in_bulk(ids)
    for p in ranking:
        p['playerobj'] = players[p['player']]
        p['teamobj'] = p['playerobj'].get_current_team()

    base['ranking'] = ranking
    # }}}

    return render_to_response('earnings.html', base)
# }}}
