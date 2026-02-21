
import React from 'react';
import PropTypes from 'prop-types';
import uniqBy from 'lodash/uniqBy';
import Select from 'antd/lib/select';
import Modal from 'antd/lib/modal';
import { wrap as wrapDialog, DialogPropType } from '@/components/DialogWrapper';

/**
 * EditQueriesDialog
 * ------------------------------------------------------------------
 * • Chips show the queries already linked to the project.
 * • Dropdown lists ONLY queries not yet linked (deduplicated).
 * • IDs are normalised to *strings* to avoid "97" vs 97 duplicates.
 * • On OK we return plain integers so the caller can POST them.
 */
class EditQueriesDialog extends React.Component {
  static propTypes = {
    dialog: DialogPropType.isRequired,
    queries: PropTypes.arrayOf(PropTypes.number),
    queryNameMap: PropTypes.object,           // { id: name }
    getAvailableQueries: PropTypes.func.isRequired,
  };

  static defaultProps = {
    queries: [],
    queryNameMap: {},
  };

  constructor(props) {
    super(props);
    // Store selected IDs as strings to ensure Set/uniq works
    this.state = {
      loading: true,
      options: [],
      selected: props.queries.map(String),   // e.g. "97"
    };
  }

  componentDidMount() {
    const { queryNameMap } = this.props;

    this.props
      .getAvailableQueries()
      .then((apiOpts) => {
        // Normalise server data to { value: "id", label }
        const opts = apiOpts.map(o => ({
          value: String(o.value),
          label: o.label,
        }));

        // 1) remove duplicate IDs coming from the server
        const unique = uniqBy(opts, 'value');

        // 2) filter out anything already selected (chips)
        const selectedSet = new Set(this.state.selected);
        const available   = unique.filter(o => !selectedSet.has(o.value));

        // 3) build chip entries with labels so tags show names
        const chips = this.state.selected.map(id => ({
          value: id,
          label: queryNameMap[id] ||
                 unique.find(o => o.value === id)?.label ||
                 `Query #${id}`,
        }));

        this.setState({
          loading: false,
          options: [...available, ...chips],
        });
      })
      .catch(() => this.setState({ loading: false }));
  }

  handleOk = () => {
    // Convert back to integers for backend API
    const ids = this.state.selected.map(id => parseInt(id, 10));
    this.props.dialog.close(ids);
  };

  render() {
    const { dialog } = this.props;
    const { loading, options, selected } = this.state;

    return (
      <Modal
        {...dialog.props}
        title="Assign Queries"
        className="shortModal"
        onOk={this.handleOk}
      >
        <Select
          mode="multiple"
          className="w-100"
          placeholder="Select queries…"
          value={selected}
          onChange={(vals) => this.setState({ selected: vals })}
          loading={loading}
          disabled={loading}
        >
          {options.map(o => (
            <Select.Option key={o.value} value={o.value}>
              {o.label}
            </Select.Option>
          ))}
        </Select>
      </Modal>
    );
  }
}

export default wrapDialog(EditQueriesDialog);
