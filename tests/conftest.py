import pytest


def make_hours(demand=200.0, solar=0.0, tariff=8.0, solar_daytime_hours=range(7, 18), solar_peak=150.0):
    hours = []
    for h in range(24):
        s = solar_peak if h in solar_daytime_hours else 0.0
        hours.append({"hour": h, "demand_kwh": demand, "solar_kwh": s, "tariff_bdt_per_kwh": tariff})
    return hours


def make_battery(capacity=500.0, initial=200.0, minimum=50.0, max_charge=100.0, max_discharge=100.0):
    return {
        "capacity_kwh": capacity,
        "initial_energy_kwh": initial,
        "minimum_energy_kwh": minimum,
        "max_charge_kwh_per_hour": max_charge,
        "max_discharge_kwh_per_hour": max_discharge,
    }


@pytest.fixture
def sample_hours():
    return make_hours()


@pytest.fixture
def sample_battery():
    return make_battery()
