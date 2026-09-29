#!/usr/bin/env python
"""Seed initial fee/tax rates into the database."""
from __future__ import annotations

from datetime import date
from app.db.session import SessionLocal
from app.db.models import FeeTaxRate


RATES = [
    # --- Broker Commission (SEBON Schedule 14) ---
    # Slab structure: 1% ≤50k, 0.9% 50k–500k, 0.8% 500k–1M, 0.7% >1M (reduced 10% from 2023-10-01)
    # Effective max = 0.275% (was 0.40% before reduction)
    FeeTaxRate(
        rate_type='broker_commission',
        rate_value=0.00275,  # 0.275% (max slab)
        rate_unit='percent',
        applies_to='all',
        description='Maximum broker commission allowed by SEBON (buy & sell). Slab: 1% ≤50k, 0.9% 50k–500k, 0.8% 500k–1M, 0.7% >1M',
        source='sebon',
        source_url='https://sebon.gov.np/uploads/uploads/PGGxrinnPErTekluvBj63QwHqFcZJKQynI0vRE2l.pdf',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2023, 10, 1),  # 10% reduction effective
    ),
    # SEBON Fee (Schedule 15)
    FeeTaxRate(
        rate_type='sebon_fee',
        rate_value=0.00015,  # 0.015%
        rate_unit='percent',
        applies_to='all',
        description='SEBON regulatory fee on transaction value',
        source='sebon',
        source_url='https://sebon.gov.np/uploads/uploads/PGGxrinnPErTekluvBj63QwHqFcZJKQynI0vRE2l.pdf',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2023, 8, 1),
    ),
    # NEPSE Transaction Fee
    FeeTaxRate(
        rate_type='nepse_fee',
        rate_value=0.00005,  # 0.005%
        rate_unit='percent',
        applies_to='all',
        description='NEPSE transaction fee on transaction value',
        source='nepse',
        source_url='https://nepalstock.com',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2023, 8, 1),
    ),
    # STT (Securities Transaction Tax) - sell side only
    FeeTaxRate(
        rate_type='stt',
        rate_value=0.0015,  # 0.15%
        rate_unit='percent',
        applies_to='all',
        description='Securities Transaction Tax (sell side only)',
        source='ird',
        source_url='https://ird.gov.np',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2023, 8, 1),
    ),
    # --- CGT Individual Long-term (>365 days) ---
    # FY 2082/83 (2025-07-17 to 2026-07-16): 5%
    FeeTaxRate(
        rate_type='cgt_individual_long',
        rate_value=0.05,  # 5%
        rate_unit='percent',
        applies_to='individual',
        description='Capital gains tax for individuals (long-term > 365 days) — FY 2082/83',
        source='ird',
        source_url='https://ird.gov.np/faq/',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2025, 7, 17),
        effective_to=date(2026, 7, 16),
    ),
    # FY 2083/84 (2026-07-17 onward): 7.5% — UNVERIFIED (Finance Act 2083 PDF not accessible)
    FeeTaxRate(
        rate_type='cgt_individual_long',
        rate_value=0.075,  # 7.5%
        rate_unit='percent',
        applies_to='individual',
        description='Capital gains tax for individuals (long-term > 365 days) — FY 2083/84 per Finance Act 2083 [UNVERIFIED: primary gazette PDF not accessible on ird.gov.np; sourced from IRD FAQ + Pradhan Law briefing]',
        source='ird',
        source_url='https://ird.gov.np/faq/',
        verification_status='unverified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2026, 7, 17),
    ),
    # --- CGT Individual Short-term (≤365 days) ---
    # FY 2082/83 (2025-07-17 to 2026-07-16): 7.5%
    FeeTaxRate(
        rate_type='cgt_individual_short',
        rate_value=0.075,  # 7.5%
        rate_unit='percent',
        applies_to='individual',
        description='Capital gains tax for individuals (short-term ≤ 365 days) — FY 2082/83',
        source='ird',
        source_url='https://ird.gov.np/faq/',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2025, 7, 17),
        effective_to=date(2026, 7, 16),
    ),
    # FY 2083/84 (2026-07-17 onward): 10% — UNVERIFIED (Finance Act 2083 PDF not accessible)
    FeeTaxRate(
        rate_type='cgt_individual_short',
        rate_value=0.10,  # 10%
        rate_unit='percent',
        applies_to='individual',
        description='Capital gains tax for individuals (short-term ≤ 365 days) — FY 2083/84 per Finance Act 2083 [UNVERIFIED: primary gazette PDF not accessible on ird.gov.np; sourced from IRD FAQ + Pradhan Law briefing]',
        source='ird',
        source_url='https://ird.gov.np/faq/',
        verification_status='unverified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2026, 7, 17),
    ),
    # CGT Entity/Company (unchanged)
    FeeTaxRate(
        rate_type='cgt_entity',
        rate_value=0.15,  # 15%
        rate_unit='percent',
        applies_to='entity',
        description='Capital gains tax for entities/companies',
        source='ird',
        source_url='https://ird.gov.np/public/pdf/1747549774.pdf',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2023, 8, 1),
    ),
    # DP Charge per transaction
    FeeTaxRate(
        rate_type='dp_charge',
        rate_value=25.0,
        rate_unit='fixed_rs',
        applies_to='all',
        description='DP charge per demat transaction',
        source='cds_clearing',
        source_url='https://cdsclearing.com.np',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2023, 8, 1),
    ),
    # DP Transaction Charge (per demat txn)
    FeeTaxRate(
        rate_type='dp_transaction',
        rate_value=25.0,
        rate_unit='fixed_rs',
        applies_to='all',
        description='DP transaction charge per demat transaction',
        source='cds_clearing',
        source_url='https://cdsclearing.com.np',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2023, 8, 1),
    ),
    # SEBON Fee (percentage-based)
    FeeTaxRate(
        rate_type='sebon_fee_pct',
        rate_value=0.00015,  # 0.015%
        rate_unit='percent',
        applies_to='all',
        description='SEBON fee as percentage of transaction value',
        source='sebon',
        source_url='https://sebon.gov.np/uploads/uploads/PGGxrinnPErTekluvBj63QwHqFcZJKQynI0vRE2l.pdf',
        verification_status='verified',
        probe_date=date(2026, 9, 28),
        effective_from=date(2023, 8, 1),
    ),
]


def main():
    """Seed the fee/tax rates."""
    session = SessionLocal()
    try:
        for rate in RATES:
            existing = session.query(FeeTaxRate).filter(
                FeeTaxRate.rate_type == rate.rate_type,
                FeeTaxRate.effective_from == rate.effective_from
            ).first()
            if not existing:
                session.add(rate)
        session.commit()
        print(f'Inserted {len(RATES)} fee/tax rates')
    except Exception as e:
        print(f'Error: {e}')
        raise
    finally:
        session.close()
        print('Done')

if __name__ == '__main__':
    main()