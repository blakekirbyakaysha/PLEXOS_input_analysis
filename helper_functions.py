"""Shared data-access and market-analysis helpers for the EM update workflow.

The module centralizes NemPoint query construction, validation, time-series
transforms, and market calculations used by the monthly runbook. It is kept
separate from charting so the same logic can be reused and validated in tests
without embedding API calls or transformation logic directly in notebooks.
"""

import datetime as dt
import io
import os
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta


NEMPOINT_URL = os.getenv("NEMPOINT_URL", "https://www.neopoint.com.au/data/query")
NEMPOINT_API_KEY_ENV = "NEMPOINT_API_KEY"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 300


class NemPointQueryError(RuntimeError):
    """Raised when NemPoint cannot return a valid market-data table."""


def _format_query_date(value: dt.datetime | dt.date) -> str:
    """Format a date or datetime for a NemPoint SQL query."""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return dt.datetime.combine(value, dt.time.min).strftime("%Y-%m-%d %H:%M:%S")


def _sql_literal(value: str) -> str:
    """Escape a string used as a SQL literal."""
    return value.replace("'", "''")


def qt_post_request(
    query_string: str,
    *,
    api_key: str | None = None,
    url: str | None = None,
    timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    required_columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Run a NemPoint CSV query with transport and schema validation."""
    resolved_api_key = api_key or os.getenv(NEMPOINT_API_KEY_ENV)
    if not resolved_api_key:
        raise NemPointQueryError(f"Set {NEMPOINT_API_KEY_ENV} before querying NemPoint.")
    if not query_string.strip():
        raise ValueError("query_string must not be empty")

    request_url = url or os.getenv('NEMPOINT_URL', NEMPOINT_URL)
    payload = {'query': query_string, 'key': resolved_api_key, 'format': 'csv'}
    try:
        response = requests.post(request_url, params=payload, timeout=timeout, verify = False)
        response.raise_for_status()
        data = pd.read_csv(io.StringIO(response.text))
    except (requests.RequestException, pd.errors.ParserError, ValueError) as exc:
        raise NemPointQueryError("NemPoint query failed") from exc

    data.columns = data.columns.str.strip()
    if required_columns:
        columns_by_case = {column.upper(): column for column in data.columns}
        missing_columns = {
            column for column in required_columns
            if column.upper() not in columns_by_case
        }
        if missing_columns:
            raise NemPointQueryError(
                f"NemPoint response is missing columns: {sorted(missing_columns)}"
            )
    return data


def build_price_query(start_date: dt.datetime | dt.date, end_date: dt.datetime | dt.date) -> str:
    """Build a price query with an inclusive end boundary."""
    start = _format_query_date(start_date)
    end = _format_query_date(end_date)
    return f"""
    select REGIONID, SETTLEMENTDATE, round(RRP,2) "Trading Price_5min"
    from MMS.DISPATCHPRICE
    where SETTLEMENTDATE >= '{start}' and SETTLEMENTDATE <= '{end}'
    and INTERVENTION = 0
    ORDER BY regionID, SETTLEMENTDATE
    """


def build_generation_query(state: str, start_date: dt.datetime | dt.date, end_date: dt.datetime | dt.date) -> str:
    """Build a fuel-generation query with an exclusive end boundary."""
    start = _format_query_date(start_date)
    end = _format_query_date(end_date)
    escaped_state = _sql_literal(state)
    return f"""
    WITH RelevantUnits AS (
        SELECT InstanceName, Fuel, Region, StartDate, EndDate
        FROM NEO.PLANTS
        WHERE DISPATCHTYPE IN ('Generator', 'Bidirectional')
        AND Region = '{escaped_state}'
        AND Fuel IS NOT NULL
    )
    SELECT ru.FUEL, ru.REGION, dl.SETTLEMENTDATE,
        SUM(CASE WHEN dl.TOTALCLEARED > 0 THEN dl.TOTALCLEARED ELSE 0 END) AS Generation
    FROM MMS.DISPATCHLOAD dl
    JOIN MMS.DISPATCHCASESOLUTION dcs
        ON dl.SETTLEMENTDATE = dcs.SETTLEMENTDATE
        AND dl.INTERVENTION = dcs.INTERVENTION
    JOIN RelevantUnits ru ON dl.DUID = ru.INSTANCENAME
    WHERE dl.SETTLEMENTDATE >= '{start}' AND dl.SETTLEMENTDATE < '{end}'
    AND ru.StartDate < dl.SETTLEMENTDATE AND ru.EndDate >= dl.SETTLEMENTDATE
    GROUP BY ru.FUEL, ru.REGION, dl.SETTLEMENTDATE
    ORDER BY dl.SETTLEMENTDATE, ru.FUEL, ru.REGION;
    """


def build_demand_query(start_date: dt.datetime | dt.date, end_date: dt.datetime | dt.date) -> str:
    """Build an operational-demand query with an exclusive end boundary."""
    start = _format_query_date(start_date)
    end = _format_query_date(end_date)
    return f"""
    SELECT REGIONID, SETTLEMENTDATE, TOTALDEMAND
    FROM MMS.DISPATCHREGIONSUM
    WHERE SETTLEMENTDATE >= '{start}' AND SETTLEMENTDATE < '{end}'
    ORDER BY REGIONID, SETTLEMENTDATE;
    """


def get_price_data(start_date, end_date):
    """Return five-minute regional prices for the requested period."""
    return qt_post_request(
        build_price_query(start_date, end_date),
        required_columns=('REGIONID', 'SETTLEMENTDATE', 'Trading Price_5min'),
    )


def get_fueltype_generation(state, start_date, end_date):
    """Return five-minute generation by fuel and region."""
    data = qt_post_request(
        build_generation_query(state, start_date, end_date),
        required_columns=('FUEL', 'REGION', 'SETTLEMENTDATE', 'Generation'),
    )
    canonical_names = {
        column.upper(): column
        for column in ('Fuel', 'Region', 'SETTLEMENTDATE', 'Generation')
    }
    return data.rename(
        columns={column: canonical_names.get(column.upper(), column) for column in data.columns}
    )


def get_operational_demand(start_date, end_date):
    """Return operational demand observations for the requested period."""
    data = qt_post_request(
        build_demand_query(start_date, end_date),
        required_columns=('REGIONID', 'SETTLEMENTDATE', 'TOTALDEMAND'),
    )
    data['SETTLEMENTDATE'] = pd.to_datetime(data['SETTLEMENTDATE'])
    return data


def add_time_columns(
    data: pd.DataFrame,
    timestamp_column: str = 'SETTLEMENTDATE',
    interval_minutes: int = 5,
) -> pd.DataFrame:
    """Return data with calendar, fiscal-year, and settlement-interval columns."""
    if timestamp_column not in data.columns:
        raise KeyError(f"Missing timestamp column: {timestamp_column}")
    if interval_minutes <= 0 or 60 % interval_minutes:
        raise ValueError("interval_minutes must be a positive divisor of 60")

    result = data.copy()
    result[timestamp_column] = pd.to_datetime(result[timestamp_column])
    timestamp = result[timestamp_column]
    result['Month'] = timestamp.dt.month
    result['Day'] = timestamp.dt.day
    result['FY'] = timestamp.dt.year + (result['Month'] > 6)
    result['Interval'] = (
        timestamp.dt.hour * 60 + timestamp.dt.minute
    ) // interval_minutes
    return result


def aggregate_to_half_hour(
    data: pd.DataFrame,
    value_column: str,
    group_columns: Iterable[str],
    timestamp_column: str = 'SETTLEMENTDATE',
) -> pd.DataFrame:
    """Average interval values into right-closed half-hour settlement periods."""
    required_columns = set(group_columns) | {timestamp_column, value_column}
    missing_columns = required_columns - set(data.columns)
    if missing_columns:
        raise KeyError(f"Missing columns: {sorted(missing_columns)}")

    result = data.copy()
    result[timestamp_column] = pd.to_datetime(result[timestamp_column])
    grouped = (
        result.groupby(
            [*group_columns, pd.Grouper(
                key=timestamp_column, freq='30min', label='right', closed='right'
            )],
            as_index=False,
        )[value_column]
        .mean()
    )
    grouped['HH'] = (
        grouped[timestamp_column].dt.hour * 2
        + grouped[timestamp_column].dt.minute // 30
    )
    return grouped


def aggregate_generation_to_half_hour(data: pd.DataFrame) -> pd.DataFrame:
    """Average five-minute generation into half-hours by fuel and region."""
    return aggregate_to_half_hour(data, 'Generation', ['Fuel', 'Region'])


def build_generation_profile(data: pd.DataFrame, state: str) -> pd.DataFrame:
    """Create an average five-minute generation profile for one state."""
    required_columns = {'Fuel', 'Region', 'Generation', 'SETTLEMENTDATE'}
    missing_columns = required_columns - set(data.columns)
    if missing_columns:
        raise KeyError(f"Missing columns: {sorted(missing_columns)}")

    state_data = add_time_columns(data[data['Region'] == state])
    grouped = state_data.groupby(
        ['Fuel', 'Region', 'Interval'],
        as_index=False,
    )['Generation'].mean()
    return grouped.pivot(index='Interval', columns='Fuel', values='Generation')


def apply_fuel_mapping(
    generation_data: pd.DataFrame,
    mapping_data: pd.DataFrame,
    fuel_column: str = 'Fuel',
    mapping_column: str = 'NeoPoint Tag',
) -> tuple[pd.DataFrame, list[str]]:
    """Apply a one-to-one fuel mapping and return unmapped fuel names.

    Unmapped generation rows are retained with missing mapping fields so the
    analyst can review them instead of losing data through deduplication.
    """
    if fuel_column not in generation_data.columns:
        raise KeyError(f"Missing generation column: {fuel_column}")
    if mapping_column not in mapping_data.columns:
        raise KeyError(f"Missing mapping column: {mapping_column}")
    if mapping_data[mapping_column].duplicated().any():
        raise ValueError(f"Mapping column must be unique: {mapping_column}")

    mapped = generation_data.merge(
        mapping_data,
        left_on=fuel_column,
        right_on=mapping_column,
        how='left',
        validate='many_to_one',
        indicator=True,
    )
    unmapped_fuels = sorted(
        mapped.loc[mapped['_merge'] == 'left_only', fuel_column].dropna().unique()
    )
    return mapped.drop(columns='_merge'), unmapped_fuels


def collect_historical_generation(
    start_date: dt.datetime,
    end_date: dt.datetime,
    state: str,
    mapping_path: str,
) -> tuple[pd.DataFrame, list[str]]:
    """Collect monthly generation, aggregate it, and apply a fuel mapping."""
    mapping_data = pd.read_excel(mapping_path)
    current_date = start_date
    generation_frames = []

    while current_date < end_date:
        next_month = current_date + relativedelta(months=1)
        monthly_generation = get_fueltype_generation(
            state, current_date, min(next_month, end_date)
        )
        monthly_generation = add_time_columns(monthly_generation)
        monthly_generation.rename(
            columns={'Generation': 'Generation (MW)'}, inplace=True
        )
        monthly_generation['Generation MWh'] = (
            monthly_generation['Generation (MW)'] * (5 / 60)
        )
        shifted_timestamp = monthly_generation['SETTLEMENTDATE'] - pd.Timedelta(
            minutes=1
        )
        monthly_generation['HH'] = (
            shifted_timestamp.dt.hour * 2
            + shifted_timestamp.dt.minute // 30
        )
        generation_frames.append(
            monthly_generation.groupby(
                ['Fuel', 'Region', 'Year', 'Month', 'HH'],
                as_index=False,
            )['Generation (MW)'].mean()
        )
        current_date = next_month

    generation_data = pd.concat(generation_frames, ignore_index=True)
    generation_data['State Fuel'] = (
        generation_data['Fuel'] + ' ' + generation_data['Region']
    )
    return apply_fuel_mapping(generation_data, mapping_data)


def calculate_gas_weighted_price(
    data: pd.DataFrame,
    price_column: str = 'Price',
    generation_column: str = 'Generation',
) -> float:
    """Calculate a generation-weighted price in dollars per MWh.

    Rows with non-positive generation are excluded because they contribute no
    generation-weighted volume. The input must contain positive total volume.
    """
    required_columns = {price_column, generation_column}
    missing_columns = required_columns - set(data.columns)
    if missing_columns:
        raise KeyError(f"Missing columns: {sorted(missing_columns)}")

    positive_generation = data[data[generation_column] > 0]
    total_generation = positive_generation[generation_column].sum()
    if total_generation <= 0:
        raise ValueError('Generation-weighted price requires positive generation')
    return float(
        (positive_generation[price_column] * positive_generation[generation_column]).sum()
        / total_generation
    )


def average_demand_by_half_hour(data: pd.DataFrame) -> pd.DataFrame:
    """Return average operational demand by half-hour and region."""
    required_columns = {'SETTLEMENTDATE', 'REGIONID', 'TOTALDEMAND'}
    missing_columns = required_columns - set(data.columns)
    if missing_columns:
        raise KeyError(f"Missing columns: {sorted(missing_columns)}")

    result = data.copy()
    result['SETTLEMENTDATE'] = pd.to_datetime(result['SETTLEMENTDATE'])
    result['HH'] = (
        result['SETTLEMENTDATE'].dt.hour * 2
        + result['SETTLEMENTDATE'].dt.minute // 30
    )
    return result.groupby(
        ['HH', 'REGIONID'],
        as_index=False,
    )['TOTALDEMAND'].mean()


def calculate_generation_delta(
    current: pd.DataFrame,
    previous: pd.DataFrame,
    value_column: str = 'Generation',
    time_column: str = 'HH',
    fuel_column: str = 'Fuel',
) -> pd.DataFrame:
    """Return a full half-hour-by-fuel delta table with missing values filled to zero."""
    required_columns = {time_column, fuel_column, value_column}
    missing_columns = required_columns - set(current.columns) | required_columns - set(previous.columns)
    if missing_columns:
        raise KeyError(f"Missing columns: {sorted(missing_columns)}")

    current_profile = (
        current.groupby([time_column, fuel_column], as_index=False)[value_column]
        .mean()
        .pivot(index=time_column, columns=fuel_column, values=value_column)
        .fillna(0.0)
    )
    previous_profile = (
        previous.groupby([time_column, fuel_column], as_index=False)[value_column]
        .mean()
        .pivot(index=time_column, columns=fuel_column, values=value_column)
        .fillna(0.0)
    )
    full_index = range(0, 48)
    full_columns = sorted(set(current_profile.columns) | set(previous_profile.columns))
    current_profile = current_profile.reindex(index=full_index, columns=full_columns, fill_value=0.0)
    previous_profile = previous_profile.reindex(index=full_index, columns=full_columns, fill_value=0.0)
    return current_profile - previous_profile


def half_hour_time_labels(half_hour_index: Iterable[int]) -> pd.DatetimeIndex:
    """Return real clock-time values for half-hour settlement intervals."""
    timestamps = []
    for value in half_hour_index:
        total_minutes = int(value) * 30
        hours, minutes = divmod(total_minutes, 60)
        timestamps.append(pd.Timestamp('2000-01-01') + pd.Timedelta(hours=hours, minutes=minutes))
    return pd.DatetimeIndex(timestamps)


def build_time_series_quality_report(
    data: pd.DataFrame,
    timestamp_column: str = 'SETTLEMENTDATE',
    group_columns: Iterable[str] = (),
    interval_minutes: int = 5,
) -> dict[str, object]:
    """Return duplicate, gap, and incomplete-day diagnostics without filling data."""
    if timestamp_column not in data.columns:
        raise KeyError(f"Missing timestamp column: {timestamp_column}")
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive")

    result = data.copy()
    result[timestamp_column] = pd.to_datetime(result[timestamp_column])
    group_columns = list(group_columns)
    key_columns = group_columns + [timestamp_column]
    duplicate_rows = int(result.duplicated(key_columns).sum())
    expected_intervals_per_day = (24 * 60) // interval_minutes
    incomplete_days = (
        result.assign(_date=result[timestamp_column].dt.date)
        .groupby(group_columns + ['_date'], dropna=False)
        .size()
        .loc[lambda values: values < expected_intervals_per_day]
        .rename('observed_intervals')
        .reset_index()
    )

    gaps = []
    grouping = result.groupby(group_columns, dropna=False) if group_columns else [(None, result)]
    for group_key, group in grouping:
        timestamps = group[timestamp_column].drop_duplicates().sort_values()
        missing = timestamps[timestamps.diff() > pd.Timedelta(minutes=interval_minutes)]
        for timestamp in missing:
            gaps.append({'group': group_key, 'after': timestamp.isoformat()})

    return {
        'row_count': len(result),
        'duplicate_key_rows': duplicate_rows,
        'incomplete_days': incomplete_days,
        'gap_count': len(gaps),
        'gaps': gaps,
    }


def calculate_spreads(
    prices: pd.DataFrame,
    durations: Iterable[float],
    start_periods: Iterable[dt.date],
    end_periods: Iterable[dt.date],
    interval_minutes: int = 5,
    incomplete_day_policy: str = 'exclude',
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Calculate daily and period spreads with explicit data-quality diagnostics.

    A day contains timestamps from midnight exclusive through the next midnight
    inclusive, matching NEM settlement timestamps. Days with fewer than the
    expected number of complete intervals or with missing price values are
    excluded by default and listed in the returned diagnostics.
    """
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError('prices must have a DatetimeIndex')
    if not prices.index.is_monotonic_increasing or not prices.index.is_unique:
        raise ValueError('prices index must be sorted and unique')
    if interval_minutes <= 0 or 1440 % interval_minutes:
        raise ValueError('interval_minutes must divide evenly into one day')
    if incomplete_day_policy not in {'exclude', 'raise'}:
        raise ValueError("incomplete_day_policy must be 'exclude' or 'raise'")

    durations = list(durations)
    start_periods = list(start_periods)
    end_periods = list(end_periods)
    if len(start_periods) != len(end_periods):
        raise ValueError('start_periods and end_periods must have equal length')
    expected_intervals = 1440 // interval_minutes
    interval_hours = interval_minutes / 60
    interval_index = (prices.index - pd.Timedelta(minutes=1)).normalize()
    daily_groups = prices.groupby(interval_index)
    valid_days = {}
    excluded_days = []
    for day, day_prices in daily_groups:
        reason = None
        if len(day_prices) != expected_intervals:
            reason = f'expected {expected_intervals} intervals, found {len(day_prices)}'
        elif day_prices.isna().any().any():
            reason = 'contains missing price values'
        if reason:
            excluded_days.append({'date': day.date().isoformat(), 'reason': reason})
        else:
            valid_days[day.date()] = day_prices

    if excluded_days and incomplete_day_policy == 'raise':
        raise ValueError(f'Incomplete or invalid days: {excluded_days}')

    diagnostics = {
        'expected_intervals_per_day': expected_intervals,
        'available_day_count': len(daily_groups),
        'valid_day_count': len(valid_days),
        'excluded_days': excluded_days,
    }
    period_spreads = pd.DataFrame(index=start_periods, dtype=float)
    daily_frames = []

    for duration in durations:
        interval_count = duration / interval_hours
        if interval_count < 1 or not interval_count.is_integer():
            raise ValueError(
                f'duration {duration} is not a whole number of {interval_minutes}-minute intervals'
            )
        interval_count = int(interval_count)
        duration_daily = {}
        for day, day_prices in valid_days.items():
            values = day_prices.to_numpy(dtype=float)
            sorted_values = np.sort(values, axis=0)
            duration_daily[day] = (
                sorted_values[-interval_count:, :].mean(axis=0)
                - sorted_values[:interval_count, :].mean(axis=0)
            )

        daily_frame = pd.DataFrame.from_dict(
            duration_daily,
            orient='index',
            columns=prices.columns,
        )
        daily_frame.index = pd.to_datetime(daily_frame.index)
        daily_frame.columns = [f'{name}.{duration:g}' for name in prices.columns]
        daily_frames.append(daily_frame)

        for start_date, end_date in zip(start_periods, end_periods):
            period_days = [
                day for day in duration_daily
                if start_date <= day < end_date
            ]
            period_values = [duration_daily[day] for day in period_days]
            if period_values:
                period_spreads.loc[start_date, daily_frame.columns] = np.mean(
                    period_values, axis=0
                )

    if daily_frames:
        daily_result = pd.concat(daily_frames, axis=1).sort_index()
    else:
        daily_result = pd.DataFrame(index=pd.DatetimeIndex([]))
    period_spreads = period_spreads.sort_index()
    return period_spreads, daily_result, diagnostics


def GetSpreads(
    Prices,
    durations,
    StartPeriods,
    EndPeriods,
    IntervalLength=5,
    incomplete_day_policy='exclude',
    return_diagnostics=False,
):
    """Backward-compatible wrapper for ``calculate_spreads``."""
    result = calculate_spreads(
        Prices,
        durations,
        StartPeriods,
        EndPeriods,
        interval_minutes=IntervalLength,
        incomplete_day_policy=incomplete_day_policy,
    )
    if return_diagnostics:
        return result
    return result[:2]


#Net
def pivot_format_data(df):
    """Pivot five-minute prices and add shared calendar/interval columns."""
    required_columns = {'SETTLEMENTDATE', 'REGIONID', 'Trading Price_5min'}
    missing_columns = required_columns - set(df.columns)
    if missing_columns:
        raise KeyError(f"Missing columns: {sorted(missing_columns)}")

    pivoted = df.pivot(
        index='SETTLEMENTDATE',
        columns='REGIONID',
        values='Trading Price_5min',
    )
    pivoted.index = pd.to_datetime(pivoted.index)
    indexed = pivoted.reset_index()
    indexed = add_time_columns(indexed)
    return indexed.set_index('SETTLEMENTDATE')