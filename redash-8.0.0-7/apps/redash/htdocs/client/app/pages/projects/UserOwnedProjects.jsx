import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types'; // Import PropTypes for validation
import { react2angular } from 'react2angular';

function UserOwnedProjects({ http }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    http
      .get('/api/user_owned_projects')
      .then((response) => {
        setProjects(response.data);
      })
      .catch(() => {
        setError('Failed to fetch projects. Please try again.');
      })
      .finally(() => setLoading(false));
  }, [http]);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (error) {
    return <div className="error-message">{error}</div>;
  }

  return (
    <nav>
      <h3>My Projects</h3>
      <ul>
        {projects.map(project => (
          <li key={project.id}>
            <a href={`/projects/${project.id}`}>{project.name}</a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

// Define prop types for the component
UserOwnedProjects.propTypes = {
  http: PropTypes.shape({
    get: PropTypes.func.isRequired, // Expect `get` to be a required function
  }).isRequired,
};

// Export the React component as an AngularJS component
export default react2angular(UserOwnedProjects, ['http']);
