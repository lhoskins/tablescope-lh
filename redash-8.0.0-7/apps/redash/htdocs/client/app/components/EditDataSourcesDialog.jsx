import React from 'react';
import PropTypes from 'prop-types';
import uniqBy from 'lodash/uniqBy';
import Select from 'antd/lib/select';
import Modal from 'antd/lib/modal';
import { wrap as wrapDialog, DialogPropType } from '@/components/DialogWrapper';

/**
 * EditDataSourcesDialog
 * ------------------------------------------------------------------
 * • Chips show the data sources already linked to the project.
 * • Dropdown lists ONLY data sources not yet linked (deduplicated).
 * • IDs are normalised to *strings* to avoid duplicates.
 * • On OK we return plain integers so the caller can POST them.
 */
class EditDataSourcesDialog extends React.Component {
  static propTypes = {
    dialog: DialogPropType.isRequired,
    dataSources: PropTypes.arrayOf(PropTypes.number),
    dataSourceNameMap: PropTypes.object,           // { id: name }
    getAvailableDataSources: PropTypes.func.isRequired,
  };

  static defaultProps = {
    dataSources: [],
    dataSourceNameMap: {},
  };

  constructor(props) {
    super(props);
    // Store selected IDs as strings to ensure Set/uniq works
    this.state = {
      loading: true,
      options: [],
      selected: props.dataSources.map(String),
    };
  }

  componentDidMount() {
    const { dataSourceNameMap } = this.props;

    this.props
      .getAvailableDataSources()
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
          label: dataSourceNameMap[id] ||
                 unique.find(o => o.value === id)?.label ||
                 `DataSource #${id}`,
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
        title="Assign Data Sources"
        className="shortModal"
        onOk={this.handleOk}
      >
        <Select
          mode="multiple"
          className="w-100"
          placeholder="Select data sources…"
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

export default wrapDialog(EditDataSourcesDialog);
