/* Project specific Javascript goes here. */
function formset_add_a_row(btn, prefix="form") {
  // var root = $(btn).closest("#form_set")[0];
  var root = document.getElementById(prefix);
  if (!root) root = btn.form;
  // var form_idx = $('form #id_form-TOTAL_FORMS').val();
  var total = root.querySelector("#id_" + prefix + "-TOTAL_FORMS");
  var form_idx = total.value;
  // var el = $('<tr>' + $('form #empty_form').html().replace(/__prefix__/g, form_idx) + '</tr>') ;
  // var el = $('<tr>' + $(root).find('#'+prefix+'_empty_form').html().replace(/__prefix__/g, form_idx) + '</tr>') ;
  var el = $(root).find('#'+prefix+'_empty_form').clone(true);
  el.attr("id",null);
  el.attr("class",null);
  el.find("[id*='__prefix__'],[name*='__prefix__']").each(function() {
    $(this).attr("id", $(this).attr("id").replace('__prefix__', form_idx));
    var name = $(this).attr("name");
    if (name) $(this).attr("name", name.replace('__prefix__', form_idx));
  });
  el.find("input[data-required]").each(function() {
    var $t = $(this);
    $t.attr({
      "required": $t.attr("data-required")
    }).removeAttr('required');
  });
  if (typeof setDatePickers == 'function') setDatePickers(el);
  // $('form #form_set').append(el);
  $(root).find('#'+prefix+'_form_set').append(el);
  // $(root).find('#'+prefix+'_form_set').append(row);
  // root.querySelector("#form_set").append(el);
  //$('form #id_form-TOTAL_FORMS').val(parseInt(form_idx) + 1);
  total.value = parseInt(form_idx) + 1;
  return false;
};

function is_email_list_unique(prefix="referees", message_template=email => `The email address entered twice: ${email}`) {
  var emails=$("#"+prefix+"_form_set input[type='email'][name$='-email'][name^='referees-']").not("[name*='__prefix__']").map(function () {if (this.value.trim() != '') return this.value;}).get().sort();
  if (emails.length) for (i in emails) if (emails.slice(parseInt(i)+1).includes(emails[i])) {
    if (prefix=="referees") $('.nav a[href="#referees"]').tab('show'); else if (prefix=="members") $('.nav a[href="#applicant"]').tab('show');
    var message=message_template(emails[i]);
    var msg_el = $("#messages");
    if (msg_el.length) {
      msg_el.append(
        $('<div class="alert alert-danger">'
          +message
          +'<button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">&times;</span></button></div>')
      )
      var scrollPos=$("#messages").offset().top; $(window).scrollTop(scrollPos);
    } else bootbox.alert(message);
    return false;
  }
  return true;
}

function formset_set_inputs(prefix="form") {
  $("#"+prefix+"_form_set tr").not("[id]").each(function() {
      $tr = $(this);
      if ($tr.find("input[type!='hidden'],select").filter(function() { return $(this).val(); }).length == 0) {
        // $(this).hide();
        $tr.find("input[required],select").each(function() {
          $(this)[0].setCustomValidity('');
          $(this).removeAttr('required');
        });
      } else {
        // $(this).show();
        $tr.find("input[data-required],select[data-required]").filter(function() { return !$(this).val(); }).each(function() {
	  let el=$(this);
	  if (el.attr("type")=="file") {
	    // workaroud - ignore 'file' fields with exiting values
	    if (!el.parent().siblings()[0]) el.attr("required", '');
	  } else el.attr("required", '');
        });
      }
  })
};
