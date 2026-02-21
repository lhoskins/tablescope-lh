// Define the controller for create table
class CreateTableCtrl {
  constructor() {
    this.selectedFile = null;
  }

  // Function to handle file selection
  handleFileSelect(files) {
    this.selectedFile = files[0];
    // You can perform further processing with the selected file here if needed
  }
}

// Define initialization function
export default function init(ngModule) {
  // Register the createTable component
  ngModule.component('createTable', {
    // Assign the template from createtable.html
    template: require('./createtable.html'), // Use webpack or similar tool for require support
    // Assign the CreateTableCtrl as the controller
    controller: CreateTableCtrl,
  });

  // Define the route configuration
  return {
    '/create_table': {
      // Specify the component to render for the route
      template: '<create-table></create-table>',
      // Set the title for the page
      title: 'Create Table',
    },
  };
}

// Set initialization flag
init.init = true;
