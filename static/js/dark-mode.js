document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (savedTheme === 'dark' || (savedTheme === 'auto' && prefersDark)) {
        document.body.classList.add('dark-mode');
    }
    
    const toggleButton = document.createElement('button');
    toggleButton.className = 'theme-toggle';
    toggleButton.innerHTML = document.body.classList.contains('dark-mode')
        ? '<i class="fas fa-sun"></i>'
        : '<i class="fas fa-moon"></i>';
    toggleButton.title = t('Toggle dark mode');
    // Place the theme toggle in the top navbar next to the sidebar/language
    // controls instead of floating over the footer.
    const navbarWidgets = document.querySelector('.navbar-widgets') ||
                          document.querySelector('.main-header .navbar-nav.ml-auto') ||
                          document.querySelector('.main-header .navbar-nav');
    if (navbarWidgets) {
        const li = document.createElement('li');
        li.className = 'nav-item d-flex align-items-center px-2';
        li.appendChild(toggleButton);
        navbarWidgets.insertBefore(li, navbarWidgets.firstChild);
    } else {
        document.body.appendChild(toggleButton);
    }
    
    toggleButton.addEventListener('click', function() {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        toggleButton.innerHTML = isDark ? '<i class="fas fa-sun"></i>' : '<i class="fas fa-moon"></i>';
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
    });
    
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (localStorage.getItem('theme') === 'auto') {
            if (e.matches) {
                document.body.classList.add('dark-mode');
                toggleButton.innerHTML = '<i class="fas fa-sun"></i>';
            } else {
                document.body.classList.remove('dark-mode');
                toggleButton.innerHTML = '<i class="fas fa-moon"></i>';
            }
        }
    });
});
