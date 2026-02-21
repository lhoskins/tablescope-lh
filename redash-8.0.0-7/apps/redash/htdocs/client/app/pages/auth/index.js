// Import components to trigger auto-initialization
import "./MFAEnrollment";
import "./MFAChallenge";

// Export empty init function to satisfy the page loader
export default function init() {
  // Components auto-initialize when their root elements are present
  return {};
}

init.init = true;
