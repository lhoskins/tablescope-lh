/* eslint-disable react/require-default-props */
/*
 * AddMembersDialog.jsx
 *
 * Project members picker used by NavigationPane.jsx.
 *
 * Enhancements (2025‑07‑21):
 *   • Chips pre‑populate with existing members (labelled by user name/email).
 *   • Dropdown shows ONLY remaining, non‑member users.
 *   • IDs normalised to strings in control; converted back to numbers on save.
 *   • Works with legacy callers that passed an array of IDs (no labels).
 *
 * Usage:
 *   <AddMembersDialog
 *     visible={isOpen}
 *     title={`Edit Members – ${project.name}`}
 *     initialSelection={[{value:'1',label:'Jane Doe'}, ...]}  // or ['1','2'] legacy
 *     options={[{value:'3',label:'John Smith'}, ...]}         // non‑members only
 *     onOk={(ids)=>{ ... }}                                  // ids => [1,3,...] numbers
 *     onCancel={()=>setOpen(false)}
 *   />
 */

import React, { useState, useEffect, useMemo } from 'react';
import PropTypes from 'prop-types';
import { Modal, Select } from 'antd';

// ------------------------------------------------------------
// Helpers
// ------------------------------------------------------------

function normaliseOne(o, fallbackLabelPrefix = 'User #') {
  if (o == null) return null;
  if (typeof o === 'object') {
    // Accept {value,label} or {key,label}
    const v = o.value != null ? o.value : o.key;
    if (v == null) return null;
    return {
      value: String(v),
      label: o.label || o.title || o.name || `${fallbackLabelPrefix}${v}`,
    };
  }
  // primitive (id)
  const v = o;
  return { value: String(v), label: `${fallbackLabelPrefix}${v}` };
}

function normaliseList(list, fallbackLabelPrefix = 'User #') {
  if (!Array.isArray(list)) return [];
  const out = [];
  list.forEach(it => {
    const n = normaliseOne(it, fallbackLabelPrefix);
    if (n) out.push(n);
  });
  return out;
}

/**
 * Convert Select's labelInValue payload into our standard shape.
 * antd v3 emits { key, label }; v4+ emits { value, label }.
 */
function fromSelectPayload(payload) {
  return payload.map(p => ({
    value: String(p.value != null ? p.value : p.key),
    label: p.label,
  }));
}

// Return sorted copy (alpha, case‑insensitive).
function sortAlpha(options) {
  return [...options].sort((a, b) =>
    String(a.label).localeCompare(String(b.label), undefined, { sensitivity: 'base' })
  );
}

// ------------------------------------------------------------
// Component
// ------------------------------------------------------------

function AddMembersDialog({
  visible,
  title,
  initialSelection,
  options,
  onOk,
  onCancel,
}) {
  // Normalise props once per open.
  const normalisedInitial = useMemo(() => {
    const result = normaliseList(initialSelection);
    console.log('[AddMembersDialog] normaliseList(initialSelection):', { initialSelection, result });
    return result;
  }, [initialSelection]);
  const normalisedOptions = useMemo(() => sortAlpha(normaliseList(options)), [options]);

  const [selected, setSelected] = useState(normalisedInitial);

  // keep selected in sync when dialog re‑opens with different project
  useEffect(() => {
    if (visible) {
      console.log('[AddMembersDialog] Setting selected to:', normalisedInitial);
      setSelected(normalisedInitial);
    }
  }, [visible, normalisedInitial]);

  const handleChange = vals => {
    // Convert simple values to {value, label} format by looking up in options
    const normalised = vals.map(val => {
      const option = normalisedOptions.find(opt => opt.value === val);
      return {
        value: val,
        label: option ? option.label : `User #${val}`,
      };
    });
    setSelected(normalised);
  };

  const handleOk = () => {
    // Convert back to numeric IDs for API
    const ids = Array.from(
      new Set(selected.map(o => Number(o.value)).filter(n => !Number.isNaN(n)))
    );
    onOk(ids);
  };

  const handleCancel = () => {
    onCancel();
  };

  // Extract just the values for the Select component (not labelInValue mode)
  const selectedValues = selected.map(s => s.value);

  return (
    <Modal
      visible={visible}
      title={title}
      onOk={handleOk}
      onCancel={handleCancel}
      okText="Save"
      width={600}
      destroyOnClose
    >
      <Select
        autoFocus
        mode="multiple"
        value={selectedValues}
        onChange={handleChange}
        style={{ width: '100%' }}
        optionFilterProp="children"
        placeholder="Select users to add…"
        maxTagCount="responsive"
        // We render children rather than using the 'options' prop for broad antd compat.
      >
        {normalisedOptions.map(opt => {
          console.log('[AddMembersDialog] Rendering option:', opt);
          return (
            <Select.Option key={opt.value} value={opt.value}>
              {opt.label}
            </Select.Option>
          );
        })}
      </Select>
    </Modal>
  );
}

AddMembersDialog.propTypes = {
  visible: PropTypes.bool.isRequired,
  title: PropTypes.string,
  // initialSelection can be array of strings/numbers or {value,label} objects.
  initialSelection: PropTypes.arrayOf(PropTypes.oneOfType([
    PropTypes.string,
    PropTypes.number,
    PropTypes.shape({ value: PropTypes.string, label: PropTypes.string }),
  ])),
  // options = non‑members only
  options: PropTypes.arrayOf(PropTypes.shape({
    value: PropTypes.string,
    label: PropTypes.string,
  })),
  onOk: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

AddMembersDialog.defaultProps = {
  title: 'Add / Remove Members',
  initialSelection: [],
  options: [],
};

export default AddMembersDialog;
