import { trim } from 'lodash';
import React, { useRef, useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import Modal from 'antd/lib/modal';
import Input from 'antd/lib/input';
import DynamicComponent from '@/components/DynamicComponent';
import { wrap as wrapDialog, DialogPropType } from '@/components/DialogWrapper';
import { $location, $http } from '@/services/ng';
import recordEvent from '@/services/recordEvent';
import { policy } from '@/services/policy';

function CreateDashboardDialog({ dialog, projectId }) {
  const [name, setName] = useState('');
  const [isValid, setIsValid] = useState(false);
  const [saveInProgress, setSaveInProgress] = useState(false);
  const inputRef = useRef();
  const isCreateDashboardEnabled = policy.isCreateDashboardEnabled();

  // ANGULAR_REMOVE_ME Replace all this with `autoFocus` attribute (it does not work
  // if dialog is opened from Angular code, but works fine if open dialog from React code)
  useEffect(() => {
    const timer = setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.focus();
      }
    }, 100);
    return () => clearTimeout(timer);
  }, []);

  function handleNameChange(event) {
    const value = trim(event.target.value);
    setName(value);
    setIsValid(value !== '');
  }

  function save() {
    if (name !== '') {
      setSaveInProgress(true);

      // Use custom API endpoint if projectId is provided, otherwise use standard endpoint
      const apiEndpoint = projectId 
        ? `api/projects/${projectId}/dashboards`
        : 'api/dashboards';

      $http.post(apiEndpoint, { name })
        .then(({ data }) => {
          if (projectId && data.project_id === projectId) {
            console.log(`Dashboard "${data.name}" created and assigned to project successfully.`);
          } else if (projectId) {
            console.log(`Dashboard "${data.name}" created successfully.`);
          }
          
          dialog.close(data);
          recordEvent('create', 'dashboard');
        })
        .catch((error) => {
          setSaveInProgress(false);
          console.error('Error creating dashboard:', error);
        });
    }
  }

  return (
    <Modal
      {...dialog.props}
      {...(isCreateDashboardEnabled ? {} : { footer: null })}
      title="New Dashboard"
      okText="Save"
      cancelText="Close"
      okButtonProps={{
        disabled: !isValid || saveInProgress,
        loading: saveInProgress,
        'data-test': 'DashboardSaveButton',
      }}
      cancelButtonProps={{
        disabled: saveInProgress,
      }}
      onOk={save}
      closable={!saveInProgress}
      maskClosable={!saveInProgress}
      wrapProps={{
        'data-test': 'CreateDashboardDialog',
      }}
    >
      <DynamicComponent name="CreateDashboardDialogExtra" disabled={!isCreateDashboardEnabled}>
        <Input
          ref={inputRef}
          defaultValue={name}
          onChange={handleNameChange}
          onPressEnter={save}
          placeholder="Dashboard Name"
          disabled={saveInProgress}
        />
      </DynamicComponent>
    </Modal>
  );
}

CreateDashboardDialog.propTypes = {
  dialog: DialogPropType.isRequired,
  projectId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
};

CreateDashboardDialog.defaultProps = {
  projectId: null,
};

export default wrapDialog(CreateDashboardDialog);
