-- Oracle Check Profile Idle Time Playbook
-- User profiles and their IDLE_TIME settings
SELECT
    p.profile,
    p.resource_name,
    p.limit,
    COUNT(u.username) AS user_count
FROM dba_profiles p
LEFT JOIN dba_users u ON u.profile = p.profile
WHERE p.resource_name = 'IDLE_TIME'
GROUP BY p.profile, p.resource_name, p.limit
ORDER BY p.profile
