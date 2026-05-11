import { AnimatePresence, motion, MotionConfig, useReducedMotion } from 'motion/react';
import { useLocation, useOutlet } from 'react-router-dom';
import { pageVariants } from '../../lib/motion';

/**
 * PageTransition — wraps <Outlet /> so that route changes fade+lift instead
 * of hard-cutting. Honors prefers-reduced-motion globally via MotionConfig.
 *
 * Usage (in App.tsx, replace <Outlet /> with <PageTransition />):
 *
 *   <main>
 *     <PageTransition />
 *   </main>
 */
export default function PageTransition() {
  const location = useLocation();
  const outlet = useOutlet();
  const reduce = useReducedMotion();

  return (
    <MotionConfig reducedMotion="user">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={location.pathname}
          variants={pageVariants}
          initial={reduce ? false : 'initial'}
          animate="enter"
          exit="exit"
          style={{ height: '100%' }}
        >
          {outlet}
        </motion.div>
      </AnimatePresence>
    </MotionConfig>
  );
}
