document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (savedTheme === 'dark' || (savedTheme === 'auto' && prefersDark)) {
        document.body.classList.add('dark-mode');
    }
    
    const toggleButton = document.createElement('button');
    toggleButton.className = 'theme-toggle';
    toggleButton.innerHTML = document.body.classList.contains('dark-mode') ? 'light' : 'dark';
    toggleButton.title = t('Toggle dark mode');
    document.body.appendChild(toggleButton);
    
    toggleButton.addEventListener('click', function() {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        toggleButton.innerHTML = isDark ? 'light' : 'dark';
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
    });
    
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (localStorage.getItem('theme') === 'auto') {
            if (e.matches) {
                document.body.classList.add('dark-mode');
                toggleButton.innerHTML = 'light';
            } else {
                document.body.classList.remove('dark-mode');
                toggleButton.innerHTML = 'dark';
            }
        }
    });
});
