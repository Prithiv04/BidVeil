/* ================= Landing Page JavaScript ================= */

// Scroll Reveal Animation
const initScrollReveal = () => {
  const revealElements = document.querySelectorAll('.scroll-reveal');

  const revealOnScroll = () => {
    const windowHeight = window.innerHeight;
    revealElements.forEach((element) => {
      const elementTop = element.getBoundingClientRect().top;
      const revealPoint = 150;

      if (elementTop < windowHeight - revealPoint) {
        element.classList.add('revealed');
      }
    });
  };

  // Initial check
  revealOnScroll();

  // Listen for scroll
  window.addEventListener('scroll', revealOnScroll, { passive: true });
};

// Mobile Menu Toggle
const initMobileMenu = () => {
  const menuBtn = document.querySelector('.nav-menu-btn');
  const navLinks = document.querySelector('.nav-links');

  if (menuBtn && navLinks) {
    menuBtn.addEventListener('click', () => {
      navLinks.classList.toggle('mobile-open');
    });

    // Close menu when clicking a link
    navLinks.querySelectorAll('.nav-link').forEach(link => {
      link.addEventListener('click', () => {
        navLinks.classList.remove('mobile-open');
      });
    });
  }
};

// Smooth Scroll for Navigation Links
const initSmoothScroll = () => {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      const targetId = this.getAttribute('href');
      if (targetId === '#') return;
      
      const targetElement = document.querySelector(targetId);
      if (targetElement) {
        e.preventDefault();
        const navHeight = document.querySelector('.landing-nav').offsetHeight;
        const targetPosition = targetElement.offsetTop - navHeight - 20;
        
        window.scrollTo({
          top: targetPosition,
          behavior: 'smooth'
        });
      }
    });
  });
};

// Initialize on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  initDossierAnimation();
  initScrollReveal();
  initMobileMenu();
  initSmoothScroll();
});
