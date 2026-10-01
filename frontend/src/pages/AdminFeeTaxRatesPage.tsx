import { useState, useEffect } from 'react';
import { admin } from '../api';
import {
  Badge,
  Table,
  Column,
  Modal,
  Pagination,
  Button,
  Input,
  Select,
  Alert,
  Loading,
  ErrorState,
  EmptyState,
} from '../components/ui';
import { formatDate } from '../utils/date';

export function AdminFeeTaxRatesPage() {
  const [rates, setRates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [filterType, setFilterType] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRate, setEditingRate] = useState<any | null>(null);
  const [formData, setFormData] = useState({
    rate_type: '',
    rate_value: '',
    rate_unit: 'percent',
    applies_to: 'all',
    description: '',
    source: '',
    source_url: '',
    verification_status: 'unverified',
    effective_from: new Date().toISOString().split('T')[0],
    effective_to: '',
  });
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  const RATE_TYPES = [
    'broker_commission',
    'sebon_fee',
    'nepse_fee',
    'dp_charge',
    'dp_transaction',
    'cgt_individual_long',
    'cgt_individual_short',
    'cgt_entity',
    'sebon_fee_pct',
  ];

  const RATE_UNITS = ['percent', 'per_transaction', 'fixed_rs'];
  const APPLIES_TO = ['individual', 'entity', 'all'];
  const SOURCES = ['sebon', 'ird', 'nepse', 'cds', 'cds_clearing'];

  const fetchRates = async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | number | boolean> = {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      };
      if (filterType) params.rate_type = filterType;
      if (activeOnly) params.active_only = true;

      const res = await admin.feeTaxRates.list(params);
      setRates(res.rates);
      setTotal(res.total);
    } catch (e: any) {
      setError(e.message || 'Failed to load rates');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRates();
  }, [page, filterType, activeOnly]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormErrors({});
    const errors: Record<string, string> = {};

    if (!formData.rate_type) errors.rate_type = 'Required';
    if (!formData.rate_value) errors.rate_value = 'Required';
    if (!formData.source) errors.source = 'Required';
    if (!formData.effective_from) errors.effective_from = 'Required';

    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      return;
    }

    try {
      const payload = {
        rate_type: formData.rate_type,
        rate_value: parseFloat(formData.rate_value),
        rate_unit: formData.rate_unit,
        applies_to: formData.applies_to,
        description: formData.description || undefined,
        source: formData.source,
        source_url: formData.source_url || undefined,
        verification_status: formData.verification_status,
        effective_from: formData.effective_from,
        effective_to: formData.effective_to || undefined,
      };

      if (editingRate) {
        await admin.feeTaxRates.update(editingRate.id, payload);
      } else {
        await admin.feeTaxRates.create(payload);
      }
      closeModal();
      fetchRates();
    } catch (e: any) {
      setFormErrors({ submit: e.message || 'Failed to save' });
    }
  };

  const openCreateModal = () => {
    setEditingRate(null);
    setFormData({
      rate_type: '',
      rate_value: '',
      rate_unit: 'percent',
      applies_to: 'all',
      description: '',
      source: '',
      source_url: '',
      verification_status: 'unverified',
      effective_from: new Date().toISOString().split('T')[0],
      effective_to: '',
    });
    setFormErrors({});
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditingRate(null);
    setFormErrors({});
  };

  const columns: Column<any>[] = [
    { key: 'rate_type', header: 'Rate Type' },
    { key: 'rate_value', header: 'Value', render: (r: any) => `${(r.rate_value * (r.rate_unit === 'percent' ? 100 : 1)).toFixed(r.rate_unit === 'percent' ? 4 : 2)} ${r.rate_unit === 'percent' ? '%' : r.rate_unit}` },
    { key: 'applies_to', header: 'Applies To' },
    { key: 'source', header: 'Source', render: (r: any) => <Badge tone={r.verification_status === 'verified' ? 'ok' : 'warn'}>{r.source} {r.verification_status === 'verified' ? '✓' : ''}</Badge> },
    { key: 'effective_from', header: 'Effective From', render: (r: any) => formatDate(r.effective_from) },
    { key: 'effective_to', header: 'Effective To', render: (r: any) => r.effective_to ? formatDate(r.effective_to) : 'Current' },
    { key: 'verification_status', header: 'Status', render: (r: any) => <Badge tone={r.verification_status === 'verified' ? 'ok' : 'warn'}>{r.verification_status}</Badge> },
  ];

  return (
    <div className="container">
      <div className="page-header">
        <h1>Fee / Tax Rate Configuration</h1>
        <p className="text-muted">
          Manage fee and tax rates with effective dates. Each rate has a source or UNVERIFIED mark.
          <br />
          <strong>No STT.</strong> Every fee/tax line must have a source or UNVERIFIED mark.
          Verify current rates with your broker.
        </p>
      </div>

      <Alert type="info">
        <strong>Rules:</strong> WAC stays the official avg cost. Lots are only for holding period and capital gains tax.
        Fees on existing transactions are NOT recomputed when rates change.
        Each rate must have a source or UNVERIFIED mark.
      </Alert>

      {error && <Alert type="error">{error}</Alert>}

      <div className="filters">
        <Select
          value={filterType}
          onChange={setFilterType}
          options={[{ value: '', label: 'All Types' }, ...RATE_TYPES.map(t => ({ value: t, label: t }))]}
          placeholder="Filter by type"
        />
        <label className="checkbox-label">
          <input type="checkbox" checked={activeOnly} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setActiveOnly(e.target.checked)} />
          Active only
        </label>
        <Button onClick={openCreateModal} className="ml-auto">Add Rate</Button>
      </div>

      {loading ? <Loading /> : error ? <ErrorState error={error} onRetry={fetchRates} /> : rates.length === 0 ? <EmptyState message="No rates found" /> : (
        <>
          <Table
            columns={columns}
            rows={rates}
            rowKey={(r) => r.id}
            empty="No rates found"
          />

          <Pagination
            currentPage={page}
            totalPages={Math.ceil(total / pageSize)}
            onPageChange={setPage}
          />
        </>
      )}

      <Modal isOpen={modalOpen} onClose={closeModal} title={editingRate ? 'Edit Rate' : 'Add Rate'}>
        <form onSubmit={handleSubmit}>
          {formErrors.submit && <Alert type="error">{formErrors.submit}</Alert>}
          
          <div className="form-row">
            <div className="form-group">
              <label>Rate Type *</label>
              <Select
                value={formData.rate_type}
                onChange={(value: string) => setFormData({ ...formData, rate_type: value })}
                options={RATE_TYPES.map(t => ({ value: t, label: t }))}
                error={formErrors.rate_type}
              />
            </div>
            <div className="form-group">
              <label>Rate Value *</label>
              <Input
                type="number"
                step="0.000001"
                value={formData.rate_value}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, rate_value: e.target.value })}
                error={formErrors.rate_value}
                placeholder="e.g., 0.00275 for 0.275%"
              />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Unit *</label>
              <Select
                value={formData.rate_unit}
                onChange={(value: string) => setFormData({ ...formData, rate_unit: value })}
                options={RATE_UNITS.map(u => ({ value: u, label: u }))}
              />
            </div>
            <div className="form-group">
              <label>Applies To *</label>
              <Select
                value={formData.applies_to}
                onChange={(value: string) => setFormData({ ...formData, applies_to: value })}
                options={APPLIES_TO.map(a => ({ value: a, label: a }))}
              />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Source *</label>
              <Select
                value={formData.source}
                onChange={(value: string) => setFormData({ ...formData, source: value })}
                options={SOURCES.map(s => ({ value: s, label: s }))}
                error={formErrors.source}
              />
            </div>
            <div className="form-group">
              <label>Verification Status</label>
              <Select
                value={formData.verification_status}
                onChange={(value: string) => setFormData({ ...formData, verification_status: value })}
                options={[
                  { value: 'unverified', label: 'Unverified' },
                  { value: 'verified', label: 'Verified' },
                ]}
              />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Effective From *</label>
              <Input
                type="date"
                value={formData.effective_from}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, effective_from: e.target.value })}
                error={formErrors.effective_from}
              />
            </div>
            <div className="form-group">
              <label>Effective To (optional)</label>
              <Input
                type="date"
                value={formData.effective_to}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, effective_to: e.target.value })}
              />
            </div>
          </div>

          <div className="form-group">
            <label>Description</label>
            <textarea
              value={formData.description}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setFormData({ ...formData, description: e.target.value })}
              rows={3}
              className="form-input"
              placeholder="Optional description"
            />
          </div>

          <div className="form-group">
            <label>Source URL</label>
            <Input
              type="url"
              value={formData.source_url}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, source_url: e.target.value })}
              placeholder="https://..."
            />
          </div>

          <div className="modal-actions">
            <Button type="button" onClick={closeModal} variant="secondary">Cancel</Button>
            <Button type="submit" disabled={loading}>
              {editingRate ? 'Update' : 'Create'}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}