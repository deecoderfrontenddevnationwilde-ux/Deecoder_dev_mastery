/* Shared bridge — sessions handled by the server via HttpOnly cookies */
window.DM = {
  /* Server version check — front-ends use this to detect an outdated app.py */
  health: function () {
    return fetch('/api/health').then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  },
  me: function () {
    return fetch('/api/auth/me').then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  },
  /* Live availability check: field = 'username' | 'email' | 'phone' */
  checkAvailable: function (field, value) {
    return fetch('/api/auth/available?field=' + encodeURIComponent(field) +
                 '&value=' + encodeURIComponent(value))
      .then(function (r) {
        if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
        return r.json();
      });
  },
  /* Alias used by some pages */
  available: function (field, value) {
    return this.checkAvailable(field, value);
  },
  /* Signup: email OR phone (at least one) + unique username + password */
  register: function (username, password, email, phone) {
    return fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        username: username,
        password: password,
        email:    email || '',
        phone:    phone || ''
      })
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          var e = new Error((data && data.error) || ('HTTP ' + r.status));
          e.status = r.status;
          e.data = data;
          throw e;
        });
      }
      return r.json();
    });
  },
  /* Login accepts username, email, OR phone.
     Optional 3rd arg `remember` → persistent session when true. */
  login: function (identifier, password, remember) {
    return fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        identifier: identifier,
        password: password,
        remember: !!remember
      })
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          var e = new Error((data && data.error) || ('HTTP ' + r.status));
          e.status = r.status;
          e.data = data;
          throw e;
        });
      }
      return r.json();
    });
  },
  logout: function () {
    return fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'same-origin'
    }).then(function (r) { return r.json(); });
  },

  /* ── Password recovery ── */
  forgotRequest: function (identifier) {
    return fetch('/api/auth/forgot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ email: identifier, identifier: identifier })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var e = new Error((data && data.error) || ('HTTP ' + r.status));
          e.status = r.status;
          e.data = data;
          throw e;
        }
        return data;
      });
    });
  },
  forgotVerify: function (identifier, code) {
    return fetch('/api/auth/forgot/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ identifier: identifier, code: code })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var e = new Error((data && data.error) || ('HTTP ' + r.status));
          e.status = r.status;
          e.data = data;
          throw e;
        }
        return data;
      });
    });
  },
  forgotReset: function (identifier, resetToken, password) {
    return fetch('/api/auth/forgot/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        identifier: identifier,
        resetToken: resetToken,
        password: password
      })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var e = new Error((data && data.error) || ('HTTP ' + r.status));
          e.status = r.status;
          e.data = data;
          throw e;
        }
        return data;
      });
    });
  },

  loadCourse: function () {
    return fetch('/api/course', { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  },
  loadBackendCourse: function () {
    return fetch('/api/backend-course', { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  },
  listVideos: function () {
    return fetch('/api/videos', { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  },
  /* Admin drag & drop upload — XHR (not fetch) so we get real upload progress */
  uploadVideo: function (file, onProgress) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload');
      xhr.withCredentials = true;
      xhr.responseType = 'json';
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(xhr.response);
        } else {
          var e = new Error('HTTP ' + xhr.status);
          e.status = xhr.status;
          reject(e);
        }
      };
      xhr.onerror = function () { var e = new Error('network'); e.status = 0; reject(e); };
      var fd = new FormData();
      fd.append('file', file, file.name);
      xhr.send(fd);
    });
  },
  saveCourse: function (data) {
    return fetch('/api/course', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(data)
    }).then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  },
  saveBackendCourse: function (data) {
    return fetch('/api/backend-course', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(data)
    }).then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  },
  changeAdminPassword: function (current, newPassword) {
    return fetch('/api/admin/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ current: current, new: newPassword })
    }).then(function (r) {
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
      return r.json();
    });
  }
};
