from .coupons import CouponsView
from .insights import InsightsView
from .overview import OverviewView
from .sessions import SessionsView
from .stations import StationsView

VIEWS = {
    'overview': OverviewView,
    'stations': StationsView,
    'sessions': SessionsView,
    'coupons': CouponsView,
    'insights': InsightsView,
}
