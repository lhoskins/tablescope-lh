import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import {
  DataGrid,
  GridColumnMenuContainer,
  SortGridMenuItems,
  GridFilterMenuItem,
  HideGridColMenuItem,
  GridColumnsMenuItem,
} from '@material-ui/data-grid';
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Box,
  ListItemIcon,
  ListItemText,
  Paper,
  Button,
} from '@material-ui/core';
import ArrowBackIcon from '@material-ui/icons/ArrowBack';

const getOrgSlug = () => window.location.pathname.split('/')[1] || 'default';

export default function DataSourceViewer({ dataSource, onBack }) {
  const [data, setData] = useState([]);
  const [columns, setColumns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const dsId = dataSource.data_source_id || dataSource.id;
  const dsName = dataSource.name || dataSource.data_source?.name;
  const tableName = dataSource.tableName;
  const isTable = dataSource.isTable;

  useEffect(() => {
    fetchDataSourceData();
  }, [dsId, tableName]);

  const fetchDataSourceData = async () => {
    setLoading(true);
    setError(null);

    try {
      const orgSlug = getOrgSlug();
      
      // Build URL based on whether it's a table or datasource
      let url;
      if (isTable && tableName) {
        // For database tables, use preview with table parameter
        url = `/${orgSlug}/api/data_sources/${dsId}/preview?table=${encodeURIComponent(tableName)}`;
        console.log('[DataSourceViewer] Fetching table data from:', url);
      } else {
        // For file datasources
        url = `/${orgSlug}/api/data_sources/${dsId}/preview`;
        console.log('[DataSourceViewer] Fetching datasource data from:', url);
      }
      
      // Fetch data from the data source
      const response = await fetch(url, { credentials: 'same-origin' });

      if (!response.ok) {
        const errorText = await response.text();
        console.error('[DataSourceViewer] Error response:', response.status, errorText);
        throw new Error(`Failed to fetch data: ${response.status} - ${errorText}`);
      }

      const result = await response.json();
      console.log('[DataSourceViewer] Received data:', result);
      
      // Check for error in response
      if (result.error) {
        throw new Error(result.error);
      }
      
      // Transform data for DataGrid
      if (result.rows && result.rows.length > 0) {
        // Create columns from the first row keys
        const firstRow = result.rows[0];
        const cols = Object.keys(firstRow).map((key) => ({
          field: key,
          headerName: key,
          width: 150,
          editable: false,
        }));
        
        // Add id to each row for DataGrid
        const rows = result.rows.map((row, index) => ({
          id: index,
          ...row,
        }));

        console.log('[DataSourceViewer] Setting columns:', cols.length, 'rows:', rows.length);
        setColumns(cols);
        setData(rows);
      } else {
        console.log('[DataSourceViewer] No rows in result');
        setColumns([]);
        setData([]);
        setError('No data returned from query');
      }
    } catch (err) {
      console.error('[DataSourceViewer] Error fetching data source data:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ background: '#fff', minHeight: '100vh', padding: '1rem' }}>
      <Box display="flex" alignItems="center" mb={2}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={onBack}
          style={{ marginRight: '1rem' }}
        >
          Back
        </Button>
        <Typography variant="h5" style={{ color: '#4472C4' }}>
          {isTable ? tableName : dsName}
        </Typography>
        {isTable && (
          <Typography variant="caption" style={{ color: '#999', marginLeft: '0.5rem' }}>
            from {dsName}
          </Typography>
        )}
      </Box>

      {error && (
        <Paper style={{ padding: '1rem', marginBottom: '1rem', backgroundColor: '#ffebee' }}>
          <Typography color="error">Error: {error}</Typography>
        </Paper>
      )}

      {loading ? (
        <Typography>Loading data...</Typography>
      ) : (
        <div style={{ height: 600, width: '100%' }}>
          <DataGrid
            rows={data}
            columns={columns}
            pageSize={25}
            rowsPerPageOptions={[10, 25, 50, 100]}
            checkboxSelection={false}
            disableSelectionOnClick
            loading={loading}
          />
        </div>
      )}
    </div>
  );
}

DataSourceViewer.propTypes = {
  dataSource: PropTypes.object.isRequired,
  onBack: PropTypes.func.isRequired,
};
