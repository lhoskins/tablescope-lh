import React from 'react';
import PropTypes from 'prop-types';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
} from '@material-ui/core';
import WarningIcon from '@material-ui/icons/Warning';

export default function ReplaceFileDialog({ open, fileName, existingName, onClose, onConfirm }) {
  if (!fileName) return null;

  const handleConfirm = () => {
    onConfirm();
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <WarningIcon style={{ color: '#ff9800' }} />
          <span>File Already Exists</span>
        </Box>
      </DialogTitle>
      
      <DialogContent>
        <Typography variant="body1" gutterBottom>
          A file or datasource with the name <strong>"{existingName || fileName}"</strong> already exists.
        </Typography>
        
        <Typography variant="body1" gutterBottom style={{ marginTop: 16 }}>
          Would you like to replace it?
        </Typography>
        
        <Typography variant="body2" color="error" style={{ marginTop: 16 }}>
          <strong>Warning:</strong> Replacing will permanently delete the existing file and all its configurations.
        </Typography>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} color="default">
          Cancel
        </Button>
        <Button 
          onClick={handleConfirm} 
          style={{ backgroundColor: '#ff9800', color: 'white' }}
          variant="contained"
        >
          Replace
        </Button>
      </DialogActions>
    </Dialog>
  );
}

ReplaceFileDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  fileName: PropTypes.string,
  existingName: PropTypes.string,
  onClose: PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired,
};
