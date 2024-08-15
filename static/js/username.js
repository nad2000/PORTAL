function setDefaultUsername(event) {
  var el = event ? event.target : this;
  if (!el.value || el.value == '') {
  var email = document.getElementById("id_email").value;
    if (email) {
      email = email.toLowerCase();
      document.getElementById("id_email").value = email;
      var parts = email.split("@");
      if (parts && parts.length > 0) {
        el.value = parts[0];
      }
    }
  }
};
