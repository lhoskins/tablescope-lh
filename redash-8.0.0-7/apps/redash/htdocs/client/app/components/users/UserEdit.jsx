import React, { Fragment } from 'react';
import { includes } from 'lodash';
import Alert from 'antd/lib/alert';
import Button from 'antd/lib/button';
import Form from 'antd/lib/form';
import Tag from 'antd/lib/tag';
import { User } from '@/services/user';
import { Group } from '@/services/group';
import { currentUser } from '@/services/auth';
import { absoluteUrl } from '@/services/utils';
import { UserProfile } from '../proptypes';
import DynamicForm from '../dynamic-form/DynamicForm';
import ChangePasswordDialog from './ChangePasswordDialog';
import InputWithCopy from '../InputWithCopy';

export default class UserEdit extends React.Component {
  static propTypes = {
    user: UserProfile.isRequired,
  };

  constructor(props) {
    super(props);
    this.state = {
      user: this.props.user,
      groups: [],
      loadingGroups: true,
      regeneratingApiKey: false,
      sendingPasswordEmail: false,
      resendingInvitation: false,
      togglingUser: false,
      mfaStatus: null,
      loadingMfaStatus: false,
      disablingMfa: false,
    };
  }

  componentDidMount() {
    Group.query((groups) => {
      this.setState({
        groups: groups.map(({ id, name }) => ({ value: id, title: name })),
        loadingGroups: false,
      });
    });
    
    // Load MFA status if admin viewing another user
    if (currentUser.isAdmin && this.props.user.id !== currentUser.id) {
      this.loadMfaStatus();
    }
  }
  
  loadMfaStatus = () => {
    this.setState({ loadingMfaStatus: true });
    
    fetch(`/api/users/${this.props.user.id}/mfa`, {
      method: 'GET',
      credentials: 'same-origin',
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to load MFA status');
        }
        return response.json();
      })
      .then((data) => {
        this.setState({ mfaStatus: data, loadingMfaStatus: false });
      })
      .catch((error) => {
        console.error('Error loading MFA status:', error);
        this.setState({ loadingMfaStatus: false });
      });
  };

  changePassword = () => {
    ChangePasswordDialog.showModal({ user: this.props.user });
  };

  sendPasswordReset = () => {
    this.setState({ sendingPasswordEmail: true });

    User.sendPasswordReset(this.state.user).then((passwordLink) => {
      this.setState({ passwordLink });
    }).finally(() => {
      this.setState({ sendingPasswordEmail: false });
    });
  };

  resendInvitation = () => {
    this.setState({ resendingInvitation: true });

    User.resendInvitation(this.state.user).then((passwordLink) => {
      this.setState({ passwordLink });
    }).finally(() => {
      this.setState({ resendingInvitation: false });
    });
  };

  regenerateApiKey = () => {
    const doRegenerate = () => {
      this.setState({ regeneratingApiKey: true });
      User.regenerateApiKey(this.state.user).then((apiKey) => {
        if (apiKey) {
          const { user } = this.state;
          this.setState({ user: { ...user, apiKey } });
        }
      }).finally(() => {
        this.setState({ regeneratingApiKey: false });
      });
    };

    Modal.confirm({
      title: 'Regenerate API Key',
      content: 'Are you sure you want to regenerate?',
      okText: 'Regenerate',
      onOk: doRegenerate,
      maskClosable: true,
      autoFocusButton: null,
    });
  };

  toggleUser = () => {
    const { user } = this.state;
    const toggleUser = user.isDisabled ? User.enableUser : User.disableUser;

    this.setState({ togglingUser: true });
    toggleUser(user).then((data) => {
      if (data) {
        this.setState({ user: User.convertUserInfo(data.data) });
      }
    }).finally(() => {
      this.setState({ togglingUser: false });
    });
  };

  saveUser = (values, successCallback, errorCallback) => {
    const data = {
      id: this.props.user.id,
      ...values,
    };

    User.save(data, (user) => {
      successCallback('Saved.');
      this.setState({ user: User.convertUserInfo(user) });
    }, (error = {}) => {
      errorCallback(error.data && error.data.message || 'Failed saving.');
    });
  };

  renderUserInfoForm() {
    const { user, groups, loadingGroups } = this.state;

    const formFields = [
      {
        name: 'name',
        title: 'Name',
        type: 'text',
        initialValue: user.name,
      },
      {
        name: 'email',
        title: 'Email',
        type: 'email',
        initialValue: user.email,
      },
      (!user.isDisabled && currentUser.id !== user.id) ? {
        name: 'group_ids',
        title: 'Groups',
        type: 'select',
        mode: 'multiple',
        options: groups,
        initialValue: groups.filter(group => includes(user.groupIds, group.value)).map(group => group.value),
        loading: loadingGroups,
        placeholder: loadingGroups ? 'Loading...' : '',
      } : {
        name: 'group_ids',
        title: 'Groups',
        type: 'content',
        content: this.renderUserGroups(),
      },
    ].map(field => ({ readOnly: user.isDisabled, required: true, ...field }));

    return (
      <DynamicForm
        fields={formFields}
        onSubmit={this.saveUser}
        hideSubmitButton={user.isDisabled}
      />
    );
  }

  renderUserGroups() {
    const { user, groups, loadingGroups } = this.state;

    return loadingGroups ? 'Loading...' : (
      <div data-test="Groups">
        {groups.filter(group => includes(user.groupIds, group.value)).map((group => (
          <Tag className="m-b-5 m-r-5" key={group.value}>
            <a href={`groups/${group.value}`}>{group.title}</a>
          </Tag>
        )))}
      </div>
    );
  }

  renderApiKey() {
    const { user, regeneratingApiKey } = this.state;

    return (
      <Form layout="vertical">
        <hr />
        <Form.Item label="API Key" className="m-b-10">
          <InputWithCopy id="apiKey" className="hide-in-percy" value={user.apiKey} data-test="ApiKey" readOnly />
        </Form.Item>
        <Button
          className="w-100"
          onClick={this.regenerateApiKey}
          loading={regeneratingApiKey}
          data-test="RegenerateApiKey"
        >
          Regenerate
        </Button>
      </Form>
    );
  }

  renderPasswordLinkAlert() {
    const { user, passwordLink } = this.state;

    return (
      <Alert
        message="Email not sent!"
        description={(
          <Fragment>
            <p>
              The mail server is not configured, please send the following link
              to <b>{user.name}</b>:
            </p>
            <InputWithCopy value={absoluteUrl(passwordLink)} readOnly />
          </Fragment>
        )}
        type="warning"
        className="m-t-20"
        afterClose={() => { this.setState({ passwordLink: null }); }}
        closable
      />
    );
  }

  renderResendInvitation() {
    return (
      <Button
        className="w-100 m-t-10"
        onClick={this.resendInvitation}
        loading={this.state.resendingInvitation}
      >
        Resend Invitation
      </Button>
    );
  }

  renderSendPasswordReset() {
    const { sendingPasswordEmail } = this.state;

    return (
      <Fragment>
        <Button
          className="w-100 m-t-10"
          onClick={this.sendPasswordReset}
          loading={sendingPasswordEmail}
        >
          Send Password Reset Email
        </Button>
      </Fragment>
    );
  }

  rendertoggleUser() {
    const { user, togglingUser } = this.state;

    return user.isDisabled ? (
      <Button className="w-100 m-t-10" type="primary" onClick={this.toggleUser} loading={togglingUser}>
        Enable User
      </Button>
    ) : (
      <Button className="w-100 m-t-10" type="danger" onClick={this.toggleUser} loading={togglingUser}>
        Disable User
      </Button>
    );
  }
  
  disableMfa = () => {
    const { user } = this.state;
    
    Modal.confirm({
      title: 'Disable MFA for User',
      content: (
        <div>
          <p>Are you sure you want to disable Multi-Factor Authentication for <strong>{user.name}</strong>?</p>
          <p>This action will:</p>
          <ul>
            <li>Remove their MFA enrollment</li>
            <li>Invalidate all backup codes</li>
            <li>Send a notification email to the user</li>
            <li>Require them to re-enroll before accessing privileged features</li>
          </ul>
          <p className="text-muted">This action will be logged in the audit log.</p>
        </div>
      ),
      okText: 'Disable MFA',
      okType: 'danger',
      cancelText: 'Cancel',
      onOk: () => {
        this.setState({ disablingMfa: true });
        
        return fetch(`/api/users/${user.id}/mfa`, {
          method: 'DELETE',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({
            reason: 'Admin disabled MFA via user management interface',
          }),
        })
          .then((response) => {
            if (!response.ok) {
              return response.json().then((data) => {
                throw new Error(data.message || 'Failed to disable MFA');
              });
            }
            return response.json();
          })
          .then(() => {
            Modal.success({
              title: 'MFA Disabled',
              content: `MFA has been successfully disabled for ${user.name}. A notification email has been sent to the user.`,
            });
            // Reload MFA status
            this.loadMfaStatus();
          })
          .catch((error) => {
            Modal.error({
              title: 'Failed to Disable MFA',
              content: error.message || 'An error occurred while disabling MFA.',
            });
          })
          .finally(() => {
            this.setState({ disablingMfa: false });
          });
      },
      maskClosable: true,
      autoFocusButton: null,
    });
  };
  
  renderAdminMfaManagement() {
    const { mfaStatus, loadingMfaStatus, disablingMfa } = this.state;
    
    if (loadingMfaStatus) {
      return (
        <div>
          <h5>Multi-Factor Authentication</h5>
          <p className="text-muted">Loading MFA status...</p>
        </div>
      );
    }
    
    if (!mfaStatus) {
      return null;
    }
    
    return (
      <div>
        <h5>Multi-Factor Authentication</h5>
        {mfaStatus.mfa_enabled ? (
          <Fragment>
            <Alert
              message="MFA Enabled"
              description={(
                <div>
                  <p><strong>Phone Number:</strong> {mfaStatus.phone_number_masked}</p>
                  <p><strong>Enrolled:</strong> {new Date(mfaStatus.enrolled_at).toLocaleString()}</p>
                  {mfaStatus.last_used_at && (
                    <p><strong>Last Used:</strong> {new Date(mfaStatus.last_used_at).toLocaleString()}</p>
                  )}
                  <p><strong>Backup Codes Remaining:</strong> {mfaStatus.backup_codes_remaining}</p>
                </div>
              )}
              type="info"
              className="m-b-10"
            />
            <Button
              className="w-100"
              type="danger"
              onClick={this.disableMfa}
              loading={disablingMfa}
            >
              Disable MFA for User
            </Button>
          </Fragment>
        ) : (
          <Alert
            message="MFA Not Enabled"
            description="This user has not enrolled in Multi-Factor Authentication."
            type="warning"
          />
        )}
      </div>
    );
  }

  render() {
    const { user, passwordLink } = this.state;

    return (
      <div className="col-md-4 col-md-offset-4">
        <img
          alt="Profile"
          src={user.profileImageUrl}
          className="profile__image"
          width="40"
        />
        <h3 className="profile__h3">{user.name}</h3>
        <hr />
        {this.renderUserInfoForm()}
        {!user.isDisabled && (
          <Fragment>
            {this.renderApiKey()}
            <hr />
            <h5>Password</h5>
            {user.id === currentUser.id && (
              <Button className="w-100 m-t-10" onClick={this.changePassword} data-test="ChangePassword">
                Change Password
              </Button>
            )}
            {(currentUser.isAdmin && user.id !== currentUser.id) && (
              <Fragment>
                {user.isInvitationPending ?
                  this.renderResendInvitation() : this.renderSendPasswordReset()}
                {passwordLink && this.renderPasswordLinkAlert()}
              </Fragment>
            )}
            <hr />
            {user.id === currentUser.id && (
              <Fragment>
                <h5>Multi-Factor Authentication</h5>
                <Button 
                  className="w-100 m-t-10" 
                  onClick={() => {
                    const orgSlug = window.location.pathname.split('/')[1];
                    // Create modal overlay
                    const modal = document.createElement('div');
                    modal.id = 'mfa-modal-overlay';
                    modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 9999; display: flex; align-items: center; justify-content: center;';
                    
                    const iframe = document.createElement('iframe');
                    iframe.src = `/${orgSlug}/profile`;
                    iframe.style.cssText = 'width: 90%; max-width: 800px; height: 80vh; border: none; border-radius: 8px; background: white;';
                    
                    modal.appendChild(iframe);
                    modal.onclick = (e) => {
                      if (e.target === modal) {
                        document.body.removeChild(modal);
                      }
                    };
                    
                    // Listen for close message from iframe
                    window.addEventListener('message', function closeModal(e) {
                      if (e.data === 'closeMFAModal') {
                        const modalEl = document.getElementById('mfa-modal-overlay');
                        if (modalEl) document.body.removeChild(modalEl);
                        window.removeEventListener('message', closeModal);
                      }
                    });
                    
                    document.body.appendChild(modal);
                  }}
                  data-test="ManageMFA"
                >
                  View MFA Settings
                </Button>
              </Fragment>
            )}
          </Fragment>
        )}
        {currentUser.isAdmin && user.id !== currentUser.id && (
          <Fragment>
            <hr />
            {this.renderAdminMfaManagement()}
          </Fragment>
        )}
        <hr />
        {currentUser.isAdmin && user.id !== currentUser.id && this.rendertoggleUser()}
      </div>
    );
  }
}
