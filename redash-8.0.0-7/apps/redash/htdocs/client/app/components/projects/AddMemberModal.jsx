import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import Modal from 'antd/lib/modal';
import Input from 'antd/lib/input';
import Select from 'antd/lib/select';
import List from 'antd/lib/list';
import Avatar from 'antd/lib/avatar';
import Button from 'antd/lib/button';
import notification from '@/services/notification';
import { debounce } from 'lodash';
import './AddMemberModal.less';

const { Option } = Select;
const { Search } = Input;

/**
 * AddMemberModal Component
 * 
 * Modal dialog for adding new members to a project.
 * Provides user search and role selection functionality.
 */
function AddMemberModal({ projectId, visible, currentUserRole, onClose, onMemberAdded }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedUser, setSelectedUser] = useState(null);
  const [selectedRole, setSelectedRole] = useState('member');
  const [searching, setSearching] = useState(false);
  const [adding, setAdding] = useState(false);

  // Debounced search function
  const debouncedSearch = debounce(async (query) => {
    if (!query || query.length < 2) {
      setSearchResults([]);
      return;
    }

    setSearching(true);
    try {
      const response = await fetch(`api/users?q=${encodeURIComponent(query)}`, {
        credentials: 'same-origin',
      });

      if (!response.ok) {
        throw new Error('Failed to search users');
      }

      const data = await response.json();
      setSearchResults(data.results || []);
    } catch (error) {
      notification.error('Failed to search users');
      console.error('Error searching users:', error);
    } finally {
      setSearching(false);
    }
  }, 300);

  useEffect(() => {
    debouncedSearch(searchQuery);
  }, [searchQuery]);

  const handleAddMember = async () => {
    if (!selectedUser) {
      notification.warning('Please select a user');
      return;
    }

    setAdding(true);
    try {
      const response = await fetch(`api/projects/${projectId}/members`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({
          user_id: selectedUser.id,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || errorData.message || 'Failed to add member');
      }

      const newMember = await response.json();

      // If a specific role was selected (not 'member'), update it
      if (selectedRole !== 'member') {
        const roleResponse = await fetch(
          `api/projects/${projectId}/members/${selectedUser.id}/role`,
          {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify({ role: selectedRole }),
          }
        );

        if (!roleResponse.ok) {
          notification.warning('Member added but failed to set role. You can update it manually.');
        } else {
          const updatedMember = await roleResponse.json();
          newMember.role = updatedMember.role;
        }
      }

      notification.success(`${selectedUser.name} added to project`);
      onMemberAdded(newMember);
      handleClose();
    } catch (error) {
      const errorMessage = error.message || 'Failed to add member';
      notification.error(errorMessage);
      console.error('Error adding member:', error);
    } finally {
      setAdding(false);
    }
  };

  const handleClose = () => {
    setSearchQuery('');
    setSearchResults([]);
    setSelectedUser(null);
    setSelectedRole('member');
    onClose();
  };

  // Filter role options based on current user's role
  const getRoleOptions = () => {
    const options = [
      { value: 'member', label: 'Project Member' },
      { value: 'designer', label: 'Designer' },
      { value: 'admin', label: 'Project Admin' },
    ];

    // Only project owners can assign the owner role
    if (currentUserRole === 'owner') {
      options.push({ value: 'owner', label: 'Project Owner' });
    }

    return options;
  };

  return (
    <Modal
      title="Add Member to Project"
      visible={visible}
      onCancel={handleClose}
      footer={[
        <Button key="cancel" onClick={handleClose}>
          Cancel
        </Button>,
        <Button
          key="add"
          type="primary"
          loading={adding}
          disabled={!selectedUser}
          onClick={handleAddMember}
        >
          Add Member
        </Button>,
      ]}
      width={600}
      className="add-member-modal"
    >
      <div className="modal-content">
        <div className="search-section">
          <label className="form-label">Search Users</label>
          <Search
            placeholder="Search by name or email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            loading={searching}
            allowClear
          />
        </div>

        {searchResults.length > 0 && (
          <div className="search-results">
            <List
              dataSource={searchResults}
              renderItem={(user) => (
                <List.Item
                  className={`user-list-item ${selectedUser?.id === user.id ? 'selected' : ''}`}
                  onClick={() => setSelectedUser(user)}
                >
                  <List.Item.Meta
                    avatar={
                      <Avatar src={user.profile_image_url}>
                        {user.name?.charAt(0).toUpperCase()}
                      </Avatar>
                    }
                    title={user.name}
                    description={user.email}
                  />
                  {selectedUser?.id === user.id && (
                    <i className="fa fa-check-circle" style={{ color: '#1890ff', fontSize: 18 }} />
                  )}
                </List.Item>
              )}
            />
          </div>
        )}

        {searchQuery && !searching && searchResults.length === 0 && (
          <div className="no-results">
            <i className="fa fa-search" style={{ fontSize: 48, color: '#d9d9d9' }} />
            <p>No users found</p>
          </div>
        )}

        {selectedUser && (
          <div className="role-selection">
            <label className="form-label">Assign Role</label>
            <Select
              value={selectedRole}
              onChange={setSelectedRole}
              style={{ width: '100%' }}
            >
              {getRoleOptions().map((option) => (
                <Option key={option.value} value={option.value}>
                  {option.label}
                </Option>
              ))}
            </Select>
            <p className="role-help-text">
              {currentUserRole === 'admin' && selectedRole === 'owner' && (
                <span className="text-muted">
                  Note: Only project owners can assign the owner role
                </span>
              )}
            </p>
          </div>
        )}
      </div>
    </Modal>
  );
}

AddMemberModal.propTypes = {
  projectId: PropTypes.number.isRequired,
  visible: PropTypes.bool.isRequired,
  currentUserRole: PropTypes.oneOf(['owner', 'admin']).isRequired,
  onClose: PropTypes.func.isRequired,
  onMemberAdded: PropTypes.func.isRequired,
};

export default AddMemberModal;
