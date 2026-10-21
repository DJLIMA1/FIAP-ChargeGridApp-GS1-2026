"""Adaptadores de carregador para a borda (ver ``base``). Puros: sem rede nem dependências."""

from . import link
from .base import ChargerLimits, Register, RegisterWrite, apply_power
from .goodwe_hca_g2 import GoodWeHcaG2

DRIVERS = {'goodwe-hca-g2': GoodWeHcaG2}

__all__ = ['DRIVERS', 'ChargerLimits', 'GoodWeHcaG2', 'Register', 'RegisterWrite', 'apply_power', 'link']
