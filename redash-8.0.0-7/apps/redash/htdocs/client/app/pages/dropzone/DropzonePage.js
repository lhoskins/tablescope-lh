/* eslint-disable react/no-unused-state, react/no-unused-class-component-methods */

import React, { Component } from 'react';
import PropTypes from 'prop-types';
import { Grid, Typography, List, ListItem } from '@material-ui/core';
import ResultWindow from './ResultWindow';
import ReplaceFileDialog from '../NavigationPane/ReplaceFileDialog';

/* ------------------------------------------------------------------ */
/* Helper Functions                                                    */
/* ------------------------------------------------------------------ */

/**
 * Reads a cookie value by its name.
 * @param {string} name - The name of the cookie to read.
 * @returns {string|null} The cookie value or null if not found.
 */
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

/**
 * Derive the current organization slug from the URL. Redash prefixes all
 * multi‑org routes with “/<orgSlug>/…”. Fallback to empty string (single‑org).
 */
const orgSlug = window.location.pathname.split('/')[1] || '';
/**
 * Convenience: base path for all internal API requests (queries, datasources).
 * Example → “/development/api” or simply “/api” (if no org slug is present).
 */
const apiBase = orgSlug ? `/${orgSlug}/api` : '/api';

async function fetchTableData(tableName, setTableData, setUploadMessages) {
  try {
    // This fetch call remains unchanged as it points to an external service.
    const response = await fetch(
      `https://amt.hopi.cloud/json/TeiidExcelImporterTest/fetchTableData?tableName=${tableName}`,
    );
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    if (Array.isArray(data)) {
      setTableData(data);
    } else {
      throw new Error('Invalid data format: Expected an array');
    }
  } catch (error) {
    // CORRECTED: Pass a string to the message handler, not an array.
    setUploadMessages(`Error fetching table data: ${error.message}`);
  }
}

/* ------------------------------------------------------------------ */
/* Component Class                                                    */
/* ------------------------------------------------------------------ */

class DropzonePage extends Component {
  constructor(props) {
    super(props);
    this.state = {
      file: null,
      uploadMessages: [],
      uploading: false,
      tableData: [],
      dragCounter: 0,
      isDragOver: false,
      replaceDialogOpen: false,
      fileToReplace: null,
      existingFileName: null,
    };
    this.fileInput = null;

    /* Bind handlers (order satisfies react/sort-comp) */
    this.onDrop = this.onDrop.bind(this);
    this.handleDragEnter = this.handleDragEnter.bind(this);
    this.handleDragLeave = this.handleDragLeave.bind(this);
    this.uploadFile = this.uploadFile.bind(this);
    this.createDatasource = this.createDatasource.bind(this);
    this.createDefaultQuery = this.createDefaultQuery.bind(this);
    this.confirmReplace = this.confirmReplace.bind(this);
    this.cancelReplace = this.cancelReplace.bind(this);
  }

  /* -------------------------------  Drag / Drop  ------------------------------- */

  onDrop(event) {
    event.preventDefault();
    if (this.state.uploading) return;

    this.setState({ dragCounter: 0, isDragOver: false });

    const files = event.dataTransfer ? event.dataTransfer.files : event.target.files;
    if (files && files.length > 0) {
      // Convert FileList to Array
      const fileArray = Array.from(files);
      this.setState({ uploading: true }, () => {
        this.uploadFilesSequentially(fileArray, 0);
      });
    }
  }

  /**
   * Check VDB status by attempting a simple query
   */
  async checkVDBReady() {
    try {
      const response = await fetch('https://amt.hopi.cloud/json/TeiidExcelImporterTest/checkVDB', {
        method: 'GET',
      });
      
      if (response.ok) {
        const data = await response.json();
        return data.status === 'ACTIVE';
      }
      return false;
    } catch (error) {
      return false;
    }
  }

  /**
   * Wait for VDB to be ready with polling
   */
  async waitForVDBReady(maxAttempts = 30) {
    for (let i = 0; i < maxAttempts; i++) {
      const isReady = await this.checkVDBReady();
      if (isReady) {
        return true;
      }
      // Wait 1 second before checking again
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    return false; // Timeout after 30 seconds
  }

  /**
   * Upload files sequentially to ensure each completes before the next starts.
   * This prevents VDB corruption and ensures proper data source creation.
   */
  uploadFilesSequentially(files, index) {
    if (index >= files.length) {
      // All files uploaded
      this.setState({ uploading: false });
      this.addUploadMessage(`✓ All ${files.length} file(s) uploaded successfully!`);
      return;
    }

    const file = files[index];
    this.addUploadMessage(`Uploading file ${index + 1} of ${files.length}: ${file.name}...`);
    
    this.uploadFile(file, false).then(() => {
      // uploadFile already waits for completion, proceed to next file
      this.uploadFilesSequentially(files, index + 1);
    }).catch((error) => {
      this.addUploadMessage(`Error uploading ${file.name}: ${error.message}`);
      // Continue with next file even if one fails
      this.uploadFilesSequentially(files, index + 1);
    });
  }

  /* -----------------------------  Datasource / Query API  ----------------------------- */

  /**
   * Creates a default "SELECT * ..." query for the new data source.
   * Uses the logged‑in session (cookies) and standard Redash API; no API key.
   * @param {number} datasourceId - The ID of the newly created data source.
   * @param {string} tableName - The name of the table, used for the query name.
   */
  createDefaultQuery = (datasourceId, tableName) => {
    const payload = {
      name: tableName,
      query: `SELECT * FROM ${tableName}`,
      data_source_id: datasourceId,
      schedule: null,
      options: { parameters: [] },
      is_draft: false,
    };

    return fetch(`${apiBase}/queries`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCookie('csrf_token'),
      },
      credentials: 'same-origin', // Ensures cookies (like session) are sent
      body: JSON.stringify(payload),
    }).then((r) => {
      if (!r.ok) {
        return r.text().then(text => {
          throw new Error(`Failed to create query. Server response: ${text}`);
        });
      }
      return r.json();
    });
  };

  /**
   * Creates a new data source via the standard API endpoint.
   * Uses the logged‑in session (cookies) and standard Redash API; no API key.
   * @param {string} tableName - The name for the new data source.
   */
  createDatasource(tableName) {
    const payload = {
      name: tableName,
      type: 'external',
      options: {},
    };

    return fetch(`${apiBase}/data_sources`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCookie('csrf_token'),
      },
      credentials: 'same-origin', // Ensures cookies (like session) are sent
      body: JSON.stringify(payload),
    })
      .then((response) => {
        if (!response.ok) {
          // Get the response text to see the HTML/error from the server
          return response.text().then(text => {
            throw new Error(`Failed to create datasource. Server response: ${text}`);
          });
        }
        return response.json();
      })
      .then((ds) => {
        this.addUploadMessage(
          `Datasource '${tableName}' (#${ds.id}) created successfully.`,
        );
        return this.createDefaultQuery(ds.id, tableName);
      })
      .then((q) => {
        this.addUploadMessage(
          `Auto-query '${q.name}' (id ${q.id}) saved successfully.`,
        );
      })
      .catch((error) => {
        // The error message will now include the server's HTML response for easier debugging.
        this.addUploadMessage(`Error creating datasource / query: ${error.message}`);
      });
  }

  /* ---------------------------  Upload & Post-Ops  ----------------------------- */

  uploadFile(file, shouldReplace = false) {
    const { onUploadComplete } = this.props;
    const formData = new FormData();
    formData.append('file', file);
    
    // Add replace parameter if this is a replacement
    if (shouldReplace) {
      formData.append('replace', 'true');
    }

    // UPDATED: Use customer folder upload API endpoint
    // This will automatically create customer folders and save files to org-specific location
    return fetch(`${apiBase}/upload`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-CSRF-Token': getCookie('csrf_token'),
      },
      body: formData,
    })
      .then(response => {
        // Check for conflict status (409 or 400 with "already exists" error)
        if (response.status === 409 || response.status === 400) {
          return response.json().then(data => {
            if (data.error && data.error.includes('already exists')) {
              // Show replace confirmation dialog
              this.setState({
                replaceDialogOpen: true,
                fileToReplace: file,
                existingFileName: file.name,
                uploading: false,
              });
              return null; // Signal that we're waiting for user confirmation
            }
            // Other 400 errors
            throw new Error(data.error || 'Upload failed');
          });
        }
        
        if (!response.ok) {
          return response.json().then(data => {
            throw new Error(data.error || `Upload failed with status: ${response.status}`);
          });
        }
        return response.json();
      })
      .then((jsonData) => {
        if (!jsonData) return; // User needs to confirm replacement
        
        if (jsonData.error) {
          this.addUploadMessage(`Upload failed: ${jsonData.error}`);
          throw new Error(jsonData.error);
        } else {
          // Success! File uploaded to customer folder
          const successMsg = shouldReplace 
            ? `✓ File '${file.name}' replaced successfully in customer folder.`
            : `✓ File '${file.name}' uploaded successfully to customer folder.`;
          this.addUploadMessage(successMsg);
          
          if (jsonData.path) {
            this.addUploadMessage(`  Saved to: ${jsonData.path}`);
          }

          const tableName = file.name
            .replace(/\./g, '_')
            .replace(/_(\w+)$/, (_, ext) => `_${ext.toUpperCase()}`);

          // Call Java servlet to insert foreign tables/views into customer VDB
          const orgId = orgSlug === 'production' ? 1 : (orgSlug === 'development' ? 2 : 1);
          this.addUploadMessage(`Updating VDB with new table definition...`);
          
          return fetch(`https://amt.hopi.cloud/json/TeiidExcelImporterTest/importExcel?org_id=${orgId}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ fileName: file.name }),
          })
          .then(servletResponse => {
            if (!servletResponse.ok) {
              throw new Error(`Servlet failed: ${servletResponse.status}`);
            }
            return servletResponse.json();
          })
          .then(servletData => {
            this.addUploadMessage(`✓ VDB updated with table '${tableName}'`);
            
            // Only create datasource if this is a new upload, not a replacement
            if (!shouldReplace) {
              // Wait for datasource and query creation to complete
              return this.createDatasource(tableName).then(() => {
                fetchTableData(
                  tableName,
                  data => this.setState({ tableData: data }),
                  msg => this.addUploadMessage(msg),
                );

                if (onUploadComplete && typeof onUploadComplete === 'function') {
                  onUploadComplete();
                }
              });
            } else {
              this.addUploadMessage(`Using existing datasource for '${tableName}'.`);
              
              fetchTableData(
                tableName,
                data => this.setState({ tableData: data }),
                msg => this.addUploadMessage(msg),
              );

              if (onUploadComplete && typeof onUploadComplete === 'function') {
                onUploadComplete();
              }
            }
          })
          .catch(servletError => {
            this.addUploadMessage(`Warning: VDB update failed - ${servletError.message}`);
            // Continue anyway - the file is uploaded, just VDB might not be updated
          });
        }
      })
      .catch((error) => {
        this.addUploadMessage(`Error during upload: ${error.message}`);
        throw error; // Re-throw so sequential upload can handle it
      });
  }

  confirmReplace() {
    const { fileToReplace } = this.state;
    this.setState({ 
      replaceDialogOpen: false,
      uploading: true,
    }, () => {
      // Upload with replace=true
      this.uploadFile(fileToReplace, true);
    });
  }

  cancelReplace() {
    this.addUploadMessage('Operation cancelled. No changes were made.');
    this.setState({ 
      replaceDialogOpen: false,
      fileToReplace: null,
      existingFileName: null,
      file: null,
    });
  }

  /* ---------------------------  Utility / Helpers  --------------------------- */

  handleDragEnter(e) {
    e.preventDefault();
    e.stopPropagation();
    this.setState(prev => ({
      dragCounter: prev.dragCounter + 1,
      isDragOver: true,
    }));
  }

  handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    this.setState((prev) => {
      const newCount = prev.dragCounter - 1;
      return { dragCounter: newCount, isDragOver: newCount > 0 };
    });
  }

  addUploadMessage(message) {
    const timestamp = Date.now();
    this.setState(prevState => ({
      uploadMessages: [
        ...prevState.uploadMessages,
        { id: timestamp, text: message },
      ],
    }));
  }

  /* ------------------------------------------------------------------ */
  /* RENDER                                                             */
  /* ------------------------------------------------------------------ */

  render() {
    const { file, uploadMessages, tableData, isDragOver, replaceDialogOpen, existingFileName } = this.state;

    const containerStyle = {
      display: 'flex',
      justifyContent: 'center',
      padding: '20px',
    };

    const dropAreaStyle = {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 800,
      height: 400,
      backgroundColor: 'rgb(253, 250, 253)',
      border: '.5px dashed rgb(253, 231, 235)',
      borderRadius: '8px',
      cursor: 'pointer',
      userSelect: 'none',
      transition: '0.15s',
    };

    return (
      <Grid
        container
        justifyContent="center"
        alignItems="flex-start"
        style={{ flexGrow: 1, backgroundColor: '#ffffff', paddingTop: 40 }}
        spacing={3}
      >
        {/* =========================  DROP ZONE  ========================= */}
        <Grid item xs={12} sm={10}>
          <div style={containerStyle}>
            <div
              style={dropAreaStyle}
              onDragEnter={this.handleDragEnter}
              onDragLeave={this.handleDragLeave}
              onDragOver={e => e.preventDefault()}
              onDrop={this.onDrop}
              onClick={() => this.fileInput.click()}
            >
              <input
                type="file"
                multiple
                style={{ display: 'none' }}
                ref={(input) => {
                  this.fileInput = input;
                }}
                onChange={this.onDrop}
              />
              <Typography
                variant="h1"
                style={{ 
                  color: '#3B82F6', 
                  fontWeight: 300,
                  fontSize: '96px',
                  lineHeight: 1,
                  pointerEvents: 'none',
                  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                  userSelect: 'none'
                }}
              >
                +
              </Typography>
            </div>
          </div>

          {file && (
            <div style={{ marginTop: 10 }}>
              <Typography variant="body2">
                File uploaded: <strong>{file.name}</strong>
              </Typography>
              <Typography variant="body2">File size: {file.size} bytes</Typography>
            </div>
          )}

          <List>
            {uploadMessages.map(msg => (
              <ListItem key={msg.id}>
                <Typography variant="caption" color="primary">
                  {/* Ensure msg.text is a string or number before rendering */}
                  {String(msg.text)}
                </Typography>
              </ListItem>
            ))}
          </List>
        </Grid>

        {/* ======================  RESULT WINDOW  ======================= */}
        <Grid item xs={12}>
          <ResultWindow jsonData={tableData} />
        </Grid>

        {/* ===================  REPLACE CONFIRMATION DIALOG  =================== */}
        <ReplaceFileDialog
          open={replaceDialogOpen}
          fileName={file ? file.name : ''}
          existingName={existingFileName}
          onClose={this.cancelReplace}
          onConfirm={this.confirmReplace}
        />
      </Grid>
    );
  }
}

DropzonePage.propTypes = {
  onUploadComplete: PropTypes.func.isRequired,
};

export default DropzonePage;