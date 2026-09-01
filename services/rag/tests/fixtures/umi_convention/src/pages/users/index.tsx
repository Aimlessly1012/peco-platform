import { fetchUsers } from '@/services/api';

export default function UserListPage() {
  const users = fetchUsers();
  return <ul>{users.length}</ul>;
}
