import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { Button, Dialog, DialogTitle, DialogContent, DialogActions, LinearProgress, Typography, List, ListItem } from '@material-ui/core';
import CloudUploadIcon from '@material-ui/icons/CloudUpload';
import ReplaceFileDialog from './ReplaceFileDialog';
import MultiFileConflictDialog from './MultiFileConflictDialog';

const getOrgSlug = () => window.location.pathname.split('/')[1] || '';
const apiBase = getOrgSlug() ? `/${getOrgSlug()}/api` : '/api';

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

export default function ProjectFileUpload({ projectId, onUploadComplete }) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [messages, setMessages] = useState([]);
  const [replaceDialogOpen, setReplaceDialogOpen] = useState(false);
  const [fileToReplace, setFileToReplace] = useState(null);
  const [existingFileName, setExistingFileName] = useState(null);
  const [multiConflictDialogOpen, setMultiConflictDialogOpen] = useState(false);
  const [conflictingFiles, setConflictingFiles] = useState([]);
  const [conflictResolution, setConflictResolution] = useState(null);
  const [pendingFiles, setPendingFiles] = useState([]);

  const addMessage = (msg) => {
    setMessages(prev => [...prev, msg]);
  };

  const findExistingDatasource = async (name) => {
    try {
      const response = await fetch(`${apiBase}/data_sources`, {
        credentials: 'same-origin',
      });
      
      if (!response.ok) return null;
      
      const datasources = await response.json();
      return datasources.find(ds => ds.name === name) || null;
    } catch (error) {
      console.error('Error finding datasource:', error);
      return null;
    }
  };

  const uploadFile = async (file, shouldReplace = false, isSingleFile = true) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('project_id', projectId); // Pass project ID for shared folder routing
    
    if (shouldReplace) {
      formData.append('replace', 'true');
    }

    try {
      // UPDATED: Use customer folder upload API endpoint
      // This will automatically create customer folders and save files to org-specific location
      // If project is shared, files will go to shared folder
      const response = await fetch(`${apiBase}/upload`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRF-Token': getCookie('csrf_token'),
        },
        body: formData,
      });

      // Handle conflict (file already exists)
      if (response.status === 409 || response.status === 400) {
        const data = await response.json().catch(() => ({}));
        
        if (data.error && data.error.includes('already exists')) {
          if (isSingleFile) {
            // For single file, show replace dialog
            setReplaceDialogOpen(true);
            setFileToReplace(file);
            setExistingFileName(file.name);
            setUploading(false);
            return null;
          } else {
            // For multiple files, return conflict status
            addMessage(`⚠️ File '${file.name}' already exists.`);
            return 'conflict';
          }
        }
        
        // Other 400 errors
        addMessage(`Upload failed: ${data.error || 'Bad request'}`);
        return null;
      }

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Upload failed with status: ${response.status}`);
      }

      const jsonData = await response.json();
      
      if (jsonData.error) {
        addMessage(`Upload failed: ${jsonData.error}`);
        return null;
      }

      // Success! File uploaded to customer folder
      const successMsg = shouldReplace 
        ? `✓ File '${file.name}' replaced successfully in customer folder.`
        : `✓ File '${file.name}' uploaded successfully to customer folder.`;
      addMessage(successMsg);
      
      if (jsonData.path) {
        addMessage(`  Saved to: ${jsonData.path}`);
      }

      const tableName = file.name
        .replace(/\./g, '_')
        .replace(/_(\w+)$/, (_, ext) => `_${ext.toUpperCase()}`);

      // Note: VDB update is handled by the upload servlet automatically
      // No need to call a separate servlet endpoint
      addMessage(`✓ VDB updated with table '${tableName}'`);

      // Create datasource and query, then assign to project
      if (!shouldReplace) {
        await createDatasourceAndQuery(tableName);
      } else {
        addMessage(`Using existing datasource for '${tableName}'.`);
      }

      return tableName;
    } catch (error) {
      addMessage(`Error during upload: ${error.message}`);
      return null;
    }
    // Note: Don't set uploading to false here - let the caller handle it
  };

  const createDatasourceAndQuery = async (tableName) => {
    try {
      // 1. Check if datasource already exists
      let datasource = await findExistingDatasource(tableName);
      
      if (datasource) {
        addMessage(`Datasource '${tableName}' already exists (#${datasource.id}), using existing.`);
      } else {
        // Create new datasource
        const dsPayload = {
          name: tableName,
          type: 'external',
          options: {},
        };

        const dsResponse = await fetch(`${apiBase}/data_sources`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': getCookie('csrf_token'),
          },
          credentials: 'same-origin',
          body: JSON.stringify(dsPayload),
        });

        if (!dsResponse.ok) {
          const text = await dsResponse.text();
          throw new Error(`Failed to create datasource: ${text}`);
        }

        datasource = await dsResponse.json();
        addMessage(`Datasource '${tableName}' (#${datasource.id}) created successfully.`);
      }

      // 2. Add datasource to project (if not already there)
      await addDatasourceToProject(datasource.id);

      // 3. Create default query
      const queryPayload = {
        name: tableName,
        query: `SELECT * FROM ${tableName}`,
        data_source_id: datasource.id,
        project_id: [projectId], // Assign to current project
        schedule: null,
        options: { parameters: [] },
        is_draft: false,
      };

      const queryResponse = await fetch(`${apiBase}/queries`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCookie('csrf_token'),
        },
        credentials: 'same-origin',
        body: JSON.stringify(queryPayload),
      });

      if (!queryResponse.ok) {
        const text = await queryResponse.text();
        throw new Error(`Failed to create query: ${text}`);
      }

      const query = await queryResponse.json();
      addMessage(`Query '${query.name}' (id ${query.id}) created and assigned to project.`);

      // 4. Execute the query to populate initial results
      await executeQuery(query.id, datasource.id);

      // Notify parent to refresh
      if (onUploadComplete) {
        onUploadComplete();
      }

    } catch (error) {
      addMessage(`Error: ${error.message}`);
    }
  };

  const pollJob = async (jobId) => {
    const jobUrl = `${apiBase}/jobs/${jobId}`;
    let retries = 60; // Poll for max 60 seconds

    while (retries > 0) {
      const jobRes = await fetch(jobUrl, { credentials: 'same-origin' });
      if (!jobRes.ok) {
        throw new Error('Job status check failed');
      }
      
      const jobResult = await jobRes.json();

      if (jobResult.job.status === 3) { // 3 = success
        const resultRes = await fetch(`${apiBase}/query_results/${jobResult.job.query_result_id}`, { 
          credentials: 'same-origin' 
        });
        if (!resultRes.ok) {
          throw new Error('Failed to fetch query result after job completion');
        }
        return resultRes.json();
      }

      if (jobResult.job.status === 4) { // 4 = error
        throw new Error(`Query execution failed: ${jobResult.job.error || 'Unknown error'}`);
      }

      // Wait 1 second before polling again
      await new Promise(resolve => setTimeout(resolve, 1000));
      retries -= 1;
    }
    throw new Error('Query execution timed out after 60 seconds');
  };

  const executeQuery = async (queryId, datasourceId) => {
    try {
      addMessage(`Executing query to populate results...`);
      
      const response = await fetch(`${apiBase}/queries/${queryId}/results`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCookie('csrf_token'),
        },
        credentials: 'same-origin',
        body: JSON.stringify({
          parameters: {},
          max_age: 0, // Force fresh execution
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to execute query`);
      }

      let result = await response.json();
      
      // If Redash returned a job, poll for completion
      if (result.job) {
        addMessage(`Waiting for query execution to complete...`);
        result = await pollJob(result.job.id);
      }

      const rowCount = result.query_result?.data?.rows?.length || 0;
      addMessage(`✓ Query executed successfully, ${rowCount} rows loaded and cached.`);
    } catch (error) {
      addMessage(`Warning: Could not execute query - ${error.message}`);
      throw error; // Re-throw so caller knows it failed
    }
  };

  const addDatasourceToProject = async (datasourceId) => {
    try {
      const response = await fetch(`${apiBase}/projects/${projectId}/data_sources`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCookie('csrf_token'),
        },
        credentials: 'same-origin',
        body: JSON.stringify({ data_source_id: datasourceId }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        // If it's already added, that's fine
        if (data.action === 'already_exists') {
          addMessage(`Datasource already in project.`);
        } else {
          throw new Error(`Failed to add datasource to project`);
        }
      } else {
        addMessage(`Datasource added to project successfully.`);
      }
    } catch (error) {
      addMessage(`Warning: ${error.message}`);
    }
  };

  const handleFileSelect = (event) => {
    const files = Array.from(event.target.files);
    if (files.length === 0) return;

    setMessages([]);
    setUploading(true);
    setPendingFiles(files);

    const isSingleFile = files.length === 1;

    // Upload files sequentially
    const uploadSequentially = async () => {
      const conflicts = [];
      
      // First pass: detect conflicts
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        addMessage(`[${i + 1}/${files.length}] Uploading ${file.name}...`);
        
        // Try to upload without replace flag to detect conflicts
        const result = await uploadFile(file, false, isSingleFile);
        
        // For single file uploads, if there's a conflict, stop and show replace dialog
        if (result === null && isSingleFile) {
          // Replace dialog will be shown, user will confirm/cancel
          // Don't set uploading to false here - dialog handles it
          return;
        }
        
        if (result === 'conflict') {
          conflicts.push(file);
        } else if (result) {
          addMessage(`✓ ${file.name} completed successfully`);
        } else {
          addMessage(`✗ ${file.name} failed`);
        }
      }
      
      // If multiple files and conflicts detected, show multi-conflict dialog
      if (!isSingleFile && conflicts.length > 0) {
        setConflictingFiles(conflicts);
        setMultiConflictDialogOpen(true);
        setUploading(false);
        return;
      }
      
      setUploading(false);
      if (files.length > 1 && conflicts.length === 0) {
        addMessage(`✓ All ${files.length} file(s) processed successfully!`);
      }
    };

    uploadSequentially();
  };

  const handleMultiConflictResolve = async (resolution) => {
    setMultiConflictDialogOpen(false);
    setConflictResolution(resolution);
    setUploading(true);

    if (resolution === 'skip_all') {
      addMessage(`Skipped ${conflictingFiles.length} conflicting file(s).`);
      setUploading(false);
      return;
    }

    if (resolution === 'replace_all') {
      addMessage(`Replacing ${conflictingFiles.length} conflicting file(s)...`);
      for (let i = 0; i < conflictingFiles.length; i++) {
        const file = conflictingFiles[i];
        addMessage(`[${i + 1}/${conflictingFiles.length}] Replacing ${file.name}...`);
        await uploadFile(file, true, false);
        addMessage(`✓ ${file.name} replaced successfully`);
      }
      setUploading(false);
      addMessage(`✓ All ${conflictingFiles.length} file(s) replaced successfully!`);
      return;
    }

    if (resolution === 'ask_each') {
      // Process each file with individual confirmation
      for (let i = 0; i < conflictingFiles.length; i++) {
        const file = conflictingFiles[i];
        // Show individual replace dialog
        setFileToReplace(file);
        setExistingFileName(file.name);
        setReplaceDialogOpen(true);
        setUploading(false);
        // Wait for user decision (handled by confirmReplace/cancelReplace)
        return;
      }
    }
  };

  const handleMultiConflictCancel = () => {
    setMultiConflictDialogOpen(false);
    setConflictingFiles([]);
    setPendingFiles([]);
    setUploading(false);
    addMessage('Upload cancelled by user.');
  };

  const confirmReplace = async () => {
    setReplaceDialogOpen(false);
    setUploading(true);
    await uploadFile(fileToReplace, true, true);
    setUploading(false);
  };

  const cancelReplace = () => {
    setReplaceDialogOpen(false);
    setFileToReplace(null);
    setExistingFileName(null);
  };

  return (
    <>
      <Button
        variant="contained"
        color="primary"
        startIcon={<CloudUploadIcon />}
        onClick={() => setDialogOpen(true)}
        style={{ marginLeft: '10px' }}
      >
        Upload Files
      </Button>

      <Dialog open={dialogOpen} onClose={() => !uploading && setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Upload Files to Project</DialogTitle>
        <DialogContent>
          <Typography variant="body2" gutterBottom>
            Select one or more files to upload. Datasources and queries will be automatically created and assigned to this project.
          </Typography>
          
          <input
            type="file"
            multiple
            onChange={handleFileSelect}
            style={{ margin: '20px 0' }}
            disabled={uploading}
          />

          {uploading && <LinearProgress style={{ marginTop: '10px' }} />}

          {messages.length > 0 && (
            <List dense style={{ marginTop: '10px', maxHeight: '200px', overflow: 'auto' }}>
              {messages.map((msg, idx) => (
                <ListItem key={idx}>
                  <Typography variant="body2">{msg}</Typography>
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)} disabled={uploading}>
            {uploading ? 'Uploading...' : 'Close'}
          </Button>
        </DialogActions>
      </Dialog>

      <ReplaceFileDialog
        open={replaceDialogOpen}
        existingFileName={existingFileName}
        onConfirm={confirmReplace}
        onCancel={cancelReplace}
      />

      <MultiFileConflictDialog
        open={multiConflictDialogOpen}
        conflictingFiles={conflictingFiles}
        onResolve={handleMultiConflictResolve}
        onCancel={handleMultiConflictCancel}
      />
    </>
  );
}

ProjectFileUpload.propTypes = {
  projectId: PropTypes.number.isRequired,
  onUploadComplete: PropTypes.func,
};
