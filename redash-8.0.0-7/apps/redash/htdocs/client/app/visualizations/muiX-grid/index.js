import React from 'react';
// eslint-disable-next-line import/no-extraneous-dependencies
import ReactDOM17 from 'react-dom17';
import PropTypes from 'prop-types';
import { registerVisualization } from '@/visualizations';
// eslint-disable-next-line import/no-extraneous-dependencies
import { DataGrid } from '@mui/x-data-grid';
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Box,
} from '@material-ui/core';

// Default options for the grid
const DEFAULT_OPTIONS = {
  rowsPerPage: 10,
};

// Editor for page size
export const XGridEditor = ({ options, onOptionsChange }) => {
  const handleChange = (event) => {
    onOptionsChange({ ...options, rowsPerPage: Number(event.target.value) });
  };

  return (
    <Box display="flex" flexDirection="column" p={2}>
      <Typography variant="subtitle1" gutterBottom>
        Table Settings
      </Typography>
      <FormControl variant="outlined" margin="dense">
        <InputLabel id="rows-per-page-label">Rows per page</InputLabel>
        <Select
          labelId="rows-per-page-label"
          value={options.rowsPerPage}
          onChange={handleChange}
          label="Rows per page"
        >
          {[5, 10, 25, 50, 100].map(n => (
            <MenuItem key={n} value={n}>
              {n}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Box>
  );
};

XGridEditor.propTypes = {
  options: PropTypes.shape({ rowsPerPage: PropTypes.number }).isRequired,
  onOptionsChange: PropTypes.func.isRequired,
};

// Renderer using MUI X DataGrid in isolated React-17 root
export class XGridRenderer extends React.Component {
  static propTypes = {
    data: PropTypes.shape({
      columns: PropTypes.arrayOf(
        PropTypes.shape({ name: PropTypes.string.isRequired }),
      ).isRequired,
      rows: PropTypes.arrayOf(PropTypes.object).isRequired,
    }).isRequired,
    options: PropTypes.shape({ rowsPerPage: PropTypes.number }).isRequired,
  };

  constructor(props) {
    super(props);
    this.containerRef = React.createRef();
  }

  componentDidMount() {
    this.mountGrid();
  }

  componentDidUpdate(prevProps) {
    if (
      prevProps.options.rowsPerPage !== this.props.options.rowsPerPage ||
      prevProps.data !== this.props.data
    ) {
      this.mountGrid();
    }
  }

  componentWillUnmount() {
    ReactDOM17.unmountComponentAtNode(this.containerRef.current);
  }

  // mountGrid moved after lifecycle methods to satisfy sort-comp
  mountGrid() {
    const {
      data: { columns, rows },
      options,
    } = this.props;
    const gridColumns = columns.map(col => ({
      field: col.name,
      headerName: col.name,
      flex: 1,
      sortable: true,
      filterable: true,
      resizable: true,
    }));
    const gridRows = rows.map((row, idx) => ({ id: idx, ...row }));

    ReactDOM17.render(
      <DataGrid
        autoHeight
        rows={gridRows}
        columns={gridColumns}
        pageSize={options.rowsPerPage}
        rowsPerPageOptions={[5, 10, 25, 50, 100]}
        pagination
        disableSelectionOnClick
      />,
      this.containerRef.current,
    );
  }

  render() {
    return <div ref={this.containerRef} style={{ width: '100%' }} />;
  }
}

// Register visualization
registerVisualization({
  type: 'mui_x_data_grid',
  name: 'MUI X Data Grid',
  getOptions: existing => ({ ...DEFAULT_OPTIONS, ...existing }),
  Renderer: XGridRenderer,
  Editor: XGridEditor,
  defaultRows: DEFAULT_OPTIONS.rowsPerPage,
  defaultColumns: 10,
});
