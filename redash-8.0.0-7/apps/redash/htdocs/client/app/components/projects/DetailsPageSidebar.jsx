import React from 'react';
import PropTypes from 'prop-types';
import Button from 'antd/lib/button';
import Divider from 'antd/lib/divider';

import * as Sidebar from '@/components/items-list/components/Sidebar';
import { ControllerType } from '@/components/items-list/ItemsList';
import DeleteProjectButton from './DeleteProjectButton';

import { currentUser } from '@/services/auth';

export default function DetailsPageSidebar({
  controller, project, items, // Removed 'group', added 'project' prop
  canAddMembers, onAddMembersClick,
  canAddDataSources, onAddDataSourcesClick,
  onProjectDeleted,
}) {
  const canRemove = project && currentUser.isAdmin && (project.type !== 'builtin');

  return (
    <React.Fragment>
      <Sidebar.Menu items={items} selected={controller.params.currentPage} />
      <Sidebar.PageSizeSelect
        className="m-b-10"
        options={controller.pageSizeOptions}
        value={controller.itemsPerPage}
        onChange={itemsPerPage => controller.updatePagination({ itemsPerPage })}
      />
      {canAddMembers && (
        <Button className="w-100 m-t-5" type="primary" onClick={onAddMembersClick}>
          <i className="fa fa-plus m-r-5" />Add Members
        </Button>
      )}
      {canAddDataSources && (
        <Button className="w-100 m-t-5" type="primary" onClick={onAddDataSourcesClick}>
          <i className="fa fa-plus m-r-5" />Add Data Sources
        </Button>
      )}
      {canRemove && (
        <React.Fragment>
          <Divider dashed className="m-t-10 m-b-10" />
          <DeleteProjectButton className="w-100" project={project} onClick={onProjectDeleted}>Delete Project</DeleteProjectButton>
        </React.Fragment>
      )}
    </React.Fragment>
  );
}

DetailsPageSidebar.propTypes = {
  controller: ControllerType.isRequired,
  project: PropTypes.object, // eslint-disable-line react/forbid-prop-types
  items: PropTypes.array.isRequired, // eslint-disable-line react/forbid-prop-types

  canAddMembers: PropTypes.bool,
  onAddMembersClick: PropTypes.func,

  canAddDataSources: PropTypes.bool,
  onAddDataSourcesClick: PropTypes.func,

  onProjectDeleted: PropTypes.func,
};

DetailsPageSidebar.defaultProps = {
  project: null,

  canAddMembers: false,
  onAddMembersClick: null,

  canAddDataSources: false,
  onAddDataSourcesClick: null,

  onProjectDeleted: null,
};
