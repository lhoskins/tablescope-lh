import React, { useState } from 'react';
import PropTypes from 'prop-types';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  RadioGroup,
  FormControlLabel,
  Radio,
  List,
  ListItem,
  ListItemText,
  Divider,
  Box,
} from '@material-ui/core';
import WarningIcon from '@material-ui/icons/Warning';

/**
 * Multi-File Conflict Dialog
 * 
 * Shows when multiple files are being uploaded and some already exist.
 * Allows user to choose: Replace All, Skip All, or Ask for Each.
 */
export default function MultiFileConflictDialog({ open, conflictingFiles, onResolve, onCancel }) {
  const [resolution, setResolution] = useState('skip_all');

  const handleConfirm = () => {
    onResolve(resolution);
  };

  const handleCancel = () => {
    setResolution('skip_all'); // Reset to default
    onCancel();
  };

  return (
    <Dialog open={open} onClose={handleCancel} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <WarningIcon color="error" />
          <span>File Conflicts Detected</span>
        </Box>
      </DialogTitle>
      
      <DialogContent>
        <Typography variant="body1" gutterBottom>
          The following {conflictingFiles.length} file(s) already exist:
        </Typography>
        
        <List dense style={{ maxHeight: 200, overflow: 'auto', marginBottom: 16 }}>
          {conflictingFiles.map((file, index) => (
            <ListItem key={index}>
              <ListItemText 
                primary={file.name}
                secondary={`Size: ${(file.size / 1024).toFixed(2)} KB`}
              />
            </ListItem>
          ))}
        </List>
        
        <Divider style={{ margin: '16px 0' }} />
        
        <Typography variant="body2" gutterBottom>
          How would you like to proceed?
        </Typography>
        
        <RadioGroup value={resolution} onChange={(e) => setResolution(e.target.value)}>
          <FormControlLabel
            value="replace_all"
            control={<Radio color="primary" />}
            label={
              <Box>
                <Typography variant="body2" style={{ fontWeight: 'bold' }}>
                  Replace All
                </Typography>
                <Typography variant="caption" color="textSecondary">
                  Overwrite all existing files with the new versions
                </Typography>
              </Box>
            }
          />
          
          <FormControlLabel
            value="skip_all"
            control={<Radio color="primary" />}
            label={
              <Box>
                <Typography variant="body2" style={{ fontWeight: 'bold' }}>
                  Skip All (Recommended)
                </Typography>
                <Typography variant="caption" color="textSecondary">
                  Keep existing files and skip uploading these files
                </Typography>
              </Box>
            }
          />
          
          <FormControlLabel
            value="ask_each"
            control={<Radio color="primary" />}
            label={
              <Box>
                <Typography variant="body2" style={{ fontWeight: 'bold' }}>
                  Ask for Each File
                </Typography>
                <Typography variant="caption" color="textSecondary">
                  Show a confirmation dialog for each conflicting file
                </Typography>
              </Box>
            }
          />
        </RadioGroup>
      </DialogContent>
      
      <DialogActions>
        <Button onClick={handleCancel} color="default">
          Cancel Upload
        </Button>
        <Button onClick={handleConfirm} color="primary" variant="contained">
          Continue
        </Button>
      </DialogActions>
    </Dialog>
  );
}

MultiFileConflictDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  conflictingFiles: PropTypes.arrayOf(
    PropTypes.shape({
      name: PropTypes.string.isRequired,
      size: PropTypes.number.isRequired,
    })
  ).isRequired,
  onResolve: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};
