import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import Select from 'antd/lib/select';
import Button from 'antd/lib/button';
import notification from '@/services/notification';

const { Option } = Select;

const ProjectTagging = ({ queryId, $http }) => {
  const [availableProjects, setAvailableProjects] = useState([]);
  const [selectedProjects, setSelectedProjects] = useState([]);

  // ✅ Define fetch function before useEffect
  const fetchAvailableProjects = () => {
    if (!$http) {
      console.error('Error: $http is undefined in ProjectTagging.');
      return;
    }

    $http
      .get(`/api/queries/${queryId}/projects`)
      .then((response) => {
        const { privateProjects, publicProjects } = response.data;
        setAvailableProjects([...privateProjects, ...publicProjects]);
      })
      .catch(() => {
        notification.error('Failed to load projects.');
      });
  };

  useEffect(() => {
    fetchAvailableProjects();
  }, []);

  const handleProjectChange = (selected) => {
    setSelectedProjects(selected);
  };

  const updateQueryProjects = () => {
    $http
      .post(`/api/queries/${queryId}/projects`, { project_ids: selectedProjects })
      .then(() => {
        notification.success('Projects updated successfully!');
      })
      .catch(() => {
        notification.error('Failed to update projects.');
      });
  };

  return (
    <div style={{ marginTop: 10 }}>
      <label htmlFor="project-select">Select Projects:</label>
      <Select
        id="project-select"
        mode="multiple"
        style={{ width: '100%' }}
        placeholder="Assign projects"
        value={selectedProjects}
        onChange={handleProjectChange}
      >
        {availableProjects.map(project => (
          <Option key={project.id} value={project.id}>
            {project.name}
          </Option>
        ))}
      </Select>
      <Button type="primary" onClick={updateQueryProjects} style={{ marginTop: 10 }}>
        Save Projects
      </Button>
    </div>
  );
};

ProjectTagging.propTypes = {
  queryId: PropTypes.number.isRequired,
  $http: PropTypes.func.isRequired,
};

export default ProjectTagging;
