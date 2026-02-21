package cloud.tablescope;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantLock;
import java.util.concurrent.TimeUnit;

/**
 * Centralized VDB Lock Manager for preventing race conditions during VDB modifications.
 * 
 * This class provides a shared locking mechanism that both TeiidExcelImporterTest and
 * VDBManagementServlet can use to ensure atomic VDB operations.
 * 
 * The lock is based on the VDB file path, ensuring that:
 * - Only one thread can modify a specific VDB at a time
 * - File uploads wait for VDB redeployment to complete
 * - VDB redeployment waits for file processing to complete
 * 
 * Usage:
 *   VDBLockManager.acquireLock(vdbFilePath);
 *   try {
 *       // Modify VDB
 *   } finally {
 *       VDBLockManager.releaseLock(vdbFilePath);
 *   }
 */
public class VDBLockManager {
    
    // Map of VDB file paths to their locks
    private static final ConcurrentHashMap<String, ReentrantLock> vdbLocks = new ConcurrentHashMap<>();
    
    // Default timeout for acquiring locks (30 seconds)
    private static final long DEFAULT_LOCK_TIMEOUT_SECONDS = 30;
    
    /**
     * Get or create a lock for a specific VDB file path.
     * 
     * @param vdbFilePath The path to the VDB file
     * @return The lock object for this VDB
     */
    private static ReentrantLock getLock(String vdbFilePath) {
        return vdbLocks.computeIfAbsent(vdbFilePath, k -> new ReentrantLock(true)); // Fair lock
    }
    
    /**
     * Acquire a lock for a VDB file with default timeout.
     * 
     * @param vdbFilePath The path to the VDB file
     * @return true if lock was acquired, false if timeout occurred
     */
    public static boolean acquireLock(String vdbFilePath) {
        return acquireLock(vdbFilePath, DEFAULT_LOCK_TIMEOUT_SECONDS);
    }
    
    /**
     * Acquire a lock for a VDB file with specified timeout.
     * 
     * @param vdbFilePath The path to the VDB file
     * @param timeoutSeconds Maximum time to wait for the lock
     * @return true if lock was acquired, false if timeout occurred
     */
    public static boolean acquireLock(String vdbFilePath, long timeoutSeconds) {
        ReentrantLock lock = getLock(vdbFilePath);
        try {
            boolean acquired = lock.tryLock(timeoutSeconds, TimeUnit.SECONDS);
            if (acquired) {
                System.out.println("[VDBLockManager] Lock acquired for: " + vdbFilePath + 
                    " (thread: " + Thread.currentThread().getName() + ")");
            } else {
                System.out.println("[VDBLockManager] Lock timeout for: " + vdbFilePath + 
                    " (thread: " + Thread.currentThread().getName() + ")");
            }
            return acquired;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            System.err.println("[VDBLockManager] Lock interrupted for: " + vdbFilePath);
            return false;
        }
    }
    
    /**
     * Release a lock for a VDB file.
     * 
     * @param vdbFilePath The path to the VDB file
     */
    public static void releaseLock(String vdbFilePath) {
        ReentrantLock lock = vdbLocks.get(vdbFilePath);
        if (lock != null && lock.isHeldByCurrentThread()) {
            lock.unlock();
            System.out.println("[VDBLockManager] Lock released for: " + vdbFilePath + 
                " (thread: " + Thread.currentThread().getName() + ")");
        }
    }
    
    /**
     * Check if a lock is currently held for a VDB file.
     * 
     * @param vdbFilePath The path to the VDB file
     * @return true if the lock is held by any thread
     */
    public static boolean isLocked(String vdbFilePath) {
        ReentrantLock lock = vdbLocks.get(vdbFilePath);
        return lock != null && lock.isLocked();
    }
    
    /**
     * Get the number of threads waiting for a lock.
     * 
     * @param vdbFilePath The path to the VDB file
     * @return Number of waiting threads
     */
    public static int getQueueLength(String vdbFilePath) {
        ReentrantLock lock = vdbLocks.get(vdbFilePath);
        return lock != null ? lock.getQueueLength() : 0;
    }
}
